"""Recompute cost sensitivity, workload-rule decisions and fixed-count fresh-day service.

Only published fleet and run-summary tables are needed. No scheduling is performed.
Usage: python decision_checks.py --results path/to/results --out path/to/output
"""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def capacities(cell, family, count):
    if family.startswith('MX'):
        heavy = {'jiang': 500, 'lightskew': 500, 'uniform': 500, 'liu': 425}.get(cell.split('_')[0], 550)
        number = int(family[-1])
        return [heavy] * number + [270] * (count - number)
    if family.startswith('L'):
        light, rest = family[1:].split('_H')
        heavy, number = map(int, rest.split('x'))
        return [heavy] * number + [int(light)] * (count - number)
    return [int(family)] * count


def capital(curves, model, qs):
    if model.startswith('power_'):
        alpha = float(model.split('_')[1])
        return sum((q / 270) ** alpha for q in qs)
    curve = curves[model]
    if model == 'affine':
        price = lambda q: curve['F'] + curve['v'] * q
    else:
        price = lambda q: curve['b0'] + curve['b1'] * q + curve['b2'] * max(0, q - curve['brk'])
    return sum(price(q) for q in qs) / price(270)


def labour(row, measure, count):
    if measure == 'shift_h':
        return 64 * count
    if measure == 'shift_ot_h':
        return 64 * count + 6 * float(row['after_h'])
    return float(row[measure])


def main(results, out):
    out.mkdir(parents=True, exist_ok=True)
    fleets = {(r['cell'], r['family']): r for r in read(results / 'main_fleets.csv') if r['K_final']}
    curves = json.loads((results / 'price_curve.json').read_text(encoding='utf-8'))['curves_ex_vat']
    reference = read(results / 'main_decisions.csv')
    workload = {(r['cell'], r['family']): int(r['K_rho']) for r in read(results / 'main_load_rule.csv')}
    costs, simple = [], []
    for decision in reference:
        cell, model, measure = (decision[k] for k in ('cell', 'model', 'labour'))
        theta = float(decision['r'])
        group = {f: row for (c, f), row in fleets.items() if c == cell}
        indexes = {f: capital(curves, model, capacities(cell, f, int(row['K_final']))) for f, row in group.items()}
        values = {f: theta * indexes[f] + labour(row, measure, int(row['K_final'])) for f, row in group.items()}
        winner, alternative = sorted(values, key=values.get)[:2]
        assert winner == decision['winner'], (cell, model, theta, measure, winner)
        gap = values[alternative] - values[winner]
        assert math.isclose(gap / values[winner], float(decision['margin']), abs_tol=1e-10)
        # Increase only the winner's whole-fleet capital index, holding its labour and all rivals fixed.
        premium = gap / (theta * indexes[winner])
        costs.append(dict(cell=cell, model=model, theta=theta, labour=measure, winner=winner,
                          alternative=alternative, winner_cost=values[winner], alternative_cost=values[alternative],
                          margin=gap / values[winner], winner_capital_premium=premium,
                          winner_only_daily_surcharge_h=gap))
        assert math.isclose(theta * indexes[winner] * (1 + premium) + labour(group[winner], measure, int(group[winner]['K_final'])),
                            values[alternative], rel_tol=1e-12)
        if measure != 'shift_h':
            continue
        proxy = {f: theta * capital(curves, model, capacities(cell, f, workload[cell, f])) + 64 * workload[cell, f]
                 for f in group}
        chosen = min(proxy, key=proxy.get)
        count, found = workload[cell, chosen], int(group[chosen]['K_final'])
        # A qualifying stored schedule embeds in the larger fleet; below K* no qualifying pool is available.
        qualified = count >= found
        excess = (proxy[chosen] / values[winner] - 1) if qualified else ''
        assert excess == '' or excess >= -1e-10
        simple.append(dict(cell=cell, model=model, theta=theta, chosen=chosen, K_rho=count, K_star=found,
                           same_type=chosen == winner, service_supported=qualified,
                           cost_excess_if_supported=excess, baseline_winner=winner))
    write(out / 'cost_flip_thresholds.csv', costs)
    write(out / 'workload_rule_decisions.csv', simple)

    fresh = read(results / 'fresh_days_fleets.csv')
    runs = read(results / 'runs_compact/fresh_days.csv')
    grouped = defaultdict(list)
    for row in runs:
        grouped[row['cell'], row['family']].append(row)
    fixed = []
    for fleet in fresh:
        key = fleet['cell'], fleet['family']
        count = int(fleet['K_start'])
        originals = dict(fleets)
        for filename in ('delay_cap_fleets.csv', 'extended_mixes_fleets.csv'):
            for row in read(results / filename):
                if filename == 'extended_mixes_fleets.csv' or row['series'].startswith('T120_'):
                    originals.setdefault((row['cell'], row['family']), row)
        assert key in originals and count == int(originals[key]['K_final']), (key, count)
        options = defaultdict(list)
        uncapped = defaultdict(list)
        for run in grouped[key]:
            if run['status'] != 'OK' or int(run['K']) > count:
                continue
            seed = int(run['seed'])
            uncapped[seed].append(run)
            if int(run['n_over']) == 0:
                options[seed].append(run)
        seeds = sorted(uncapped)
        assert seeds == list(range(601, 631)), (key, seeds)
        selected = [max(options[s], key=lambda x: (int(x['on_time']), -float(x['crew_veh_h'])))
                    for s in seeds if options[s]]
        blocks = 97 * len(seeds)
        on = sum(int(row['on_time']) for row in selected)
        qualified = len(selected) == len(seeds) and on >= math.ceil(0.95 * blocks - 1e-9)
        fixed.append(dict(cell=key[0], family=key[1], original_count=count, new_count=int(fleet['K_final']),
                          days_with_capped_schedule=len(selected), days=len(seeds), on_time_capped_pool=on,
                          total_blocks=blocks, capped_pool_on_time_share=on / blocks,
                          max_lateness_selected_s=max(int(row['max_tard_s']) for row in selected),
                          missing_capped_days=' '.join(str(s) for s in seeds if not options[s]),
                          min_found_max_lateness_on_missing_day_s=max(
                              (min(int(r['max_tard_s']) for r in uncapped[s]) for s in seeds if not options[s]), default=0),
                          qualifies=qualified))
        assert qualified == (int(fleet['K_final']) <= count), key
    write(out / 'fresh_days_fixed_count.csv', fixed)

    cap = read(results / 'delay_cap_fleets.csv')
    verified = 0
    fields = ['K_final', 'on_time', 'crew_veh_h', 'crew_team_h', 'after_h', 'coop_share']
    by_key = {(row['series'].split('_')[0], row['cell'], row['family']): row for row in cap}
    for (level, cell, family), row in by_key.items():
        if family.startswith('MX'):
            heavy = {'jiang': 500, 'uniform': 500, 'liu': 425}[cell.split('_')[0]]
            canonical = 'L270_H%dx%s' % (heavy, family[-1])
            if (level, cell, canonical) in by_key:
                other = by_key[level, cell, canonical]
                assert all(math.isclose(float(row[k]), float(other[k]), abs_tol=1e-10) for k in fields), (level, cell)
                verified += 1
    lower = []
    lower_types = set()
    for (level, cell, family), row in by_key.items():
        if level != 'Tinf':
            continue
        original = by_key.get(('T120', cell, family), fleets.get((cell, family)))
        assert original is not None, (cell, family)
        if int(row['K_final']) < int(original['K_final']):
            assert int(row['K_final']) + 1 == int(original['K_final'])
            qs = capacities(cell, family, int(row['K_final']))
            lower.append((cell, tuple(sorted(qs))))
            lower_types.add(tuple(sorted(set(qs))) + (qs.count(max(qs)),) if len(set(qs)) > 1 else (qs[0],))
    premiums = [r['winner_capital_premium'] for r in costs]
    supported = [r for r in simple if r['service_supported']]
    summary = dict(
        cost=dict(decisions=len(costs), median_margin=statistics.median(r['margin'] for r in costs),
                  median_winner_capital_premium=statistics.median(premiums),
                  capital_premium_below_0_05=sum(x < 0.05 for x in premiums),
                  capital_premium_below_0_10=sum(x < 0.10 for x in premiums),
                  median_winner_only_surcharge_h=statistics.median(r['winner_only_daily_surcharge_h'] for r in costs)),
        workload=dict(decisions=len(simple), same_type=sum(r['same_type'] for r in simple),
                      service_supported=len(supported), service_not_supported=len(simple) - len(supported),
                      median_excess_supported=statistics.median(r['cost_excess_if_supported'] for r in supported),
                      positive_excess_supported=sum(r['cost_excess_if_supported'] > 1e-10 for r in supported),
                      excess_above_0_05_supported=sum(r['cost_excess_if_supported'] > 0.05 for r in supported),
                      max_excess_supported=max(r['cost_excess_if_supported'] for r in supported)),
        fixed_fresh=dict(fleets=len(fixed), qualifying=sum(r['qualifies'] for r in fixed),
                         original_count_changes=dict((str(d), sum(r['new_count'] - r['original_count'] == d for r in fixed))
                                                     for d in (-1, 0, 1)),
                         exceptions=[r for r in fixed if not r['qualifies']]),
        cap_aliases=dict(matched_summary_pairs=verified, lower_count_labels=len(lower), distinct_fleets=len(set(lower)),
                        distinct_types=len(lower_types))
    )
    (out / 'decision_checks.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    main(args.results.resolve(), args.out.resolve())
