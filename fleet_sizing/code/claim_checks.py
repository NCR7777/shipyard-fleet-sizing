"""Recompute manuscript statistics and procurement choices from released tables.

Uses the Python standard library. No schedule generation or optimiser is run.
Search-depth comparisons change K only; working-time and overtime terms come
from the final schedules in main_fleets.csv.

python fleet_sizing/code/claim_checks.py
python fleet_sizing/code/claim_checks.py --results fleet_sizing/results --out table_check_output
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import statistics


LABOUR = ('shift_h', 'crew_veh_h', 'crew_team_h', 'shift_ot_h')
COVER = {'jiang': 500, 'lightskew': 500, 'uniform': 500, 'liu': 425}
LEVELS = ('cp0', 'cp100', 'cp300', 'single')
SLOW_LEVELS = ('speedliu', 'speed0.5', 'speed0.75', 'hand1.5', 'hand2.0')


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def quantiles(values):
    v = sorted(float(x) for x in values)
    return dict(n=len(v), median=statistics.median(v),
                p10=v[int(0.1 * (len(v) - 1))], p90=v[int(0.9 * (len(v) - 1))],
                min=v[0], max=v[-1])


def correlation(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    return sum(x * y for x, y in zip(dx, dy)) / math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))


def capacities(cell, family, count):
    if family.startswith('MX'):
        heavy_n = int(family[-1])
        return [COVER.get(cell.split('_')[0], 550)] * heavy_n + [270] * (count - heavy_n)
    if family.startswith('L'):
        light, heavy = family[1:].split('_H')
        heavy_q, heavy_n = (int(v) for v in heavy.split('x'))
        return [heavy_q] * heavy_n + [int(light)] * (count - heavy_n)
    return [int(family)] * count


def price(q, model, curves):
    if model.startswith('power_'):
        return (q / 270) ** float(model.split('_')[1])
    if model == 'affine':
        c = curves['affine']
        return (c['F'] + c['v'] * q) / (c['F'] + c['v'] * 270)
    assert model == 'piecewise', model
    c = curves['piecewise']
    p = lambda value: c['b0'] + c['b1'] * value + c['b2'] * max(0, value - c['brk'])
    return p(q) / p(270)


def cost(row, count, model, theta, labour, curves):
    capital = sum(price(q, model, curves) for q in capacities(row['cell'], row['family'], count))
    if labour == 'shift_h':
        labour_cost = 64 * count
    elif labour == 'shift_ot_h':
        labour_cost = 64 * count + 6 * float(row['after_h'])
    else:
        labour_cost = float(row[labour])
    return theta * capital + labour_cost


def cheapest(rows, count_field, model, theta, labour, curves):
    candidates = [(cost(row, int(float(row[count_field])), model, theta, labour, curves), row['family'])
                  for row in rows if row[count_field] not in ('', 'None', None)]
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def decomposition(results, out):
    fleets = read_csv(results / 'main_fleets.csv')
    keys = {(r['cell'], r['family']) for r in fleets}
    rows = read_csv(results / 'vehicle_time_series.csv')
    pairs = read_csv(results / 'vehicle_time_pairs.csv')
    selected = lambda p: (not p['cell'].startswith('extraheavy') and
                          float(p['coup_block_share']) > 0.01 and float(p['d_work_h']) > 0)
    main_rows = [r for r in rows if (r['cell'], r['family']) in keys]
    assert len(main_rows) == len(keys) == 384
    main_pairs = [p for p in pairs if (p['cell'], p['family']) in keys and selected(p)]
    full_pairs = [p for p in pairs if selected(p)]

    def stats(ps):
        return dict(pairs=len(ps), occupancy_share=quantiles(p['share_excess'] for p in ps),
                    waiting_share=quantiles(p['share_sync'] for p in ps),
                    corr_h_occ_vs_rel_work=correlation([float(p['h_occ']) for p in ps], [float(p['rel_work']) for p in ps]))

    main = dict(scope='main study only', series=len(main_rows),
                selection='outside heavy-tail profile; coupled-block share > 0.01; extra working time > 0',
                sync_share_all=quantiles(r['sync_share'] for r in main_rows), **stats(main_pairs))
    write_json(out / 'vehicle_time_main_summary.json', main)
    write_csv(out / 'vehicle_time_main_pairs.csv', main_pairs)
    return dict(main=main, main_and_additional_mixes=stats(full_pairs),
                additional_pairs=len(full_pairs) - len(main_pairs))


def search_depth(results, out, curves):
    fleets = read_csv(results / 'main_fleets.csv')
    depth = {(r['cell'], r['family']): r for r in read_csv(results / 'main_search_levels.csv')}
    grouped = defaultdict(list)
    for row in fleets:
        d = depth[row['cell'], row['family']]
        for lev in (*LEVELS, 'final'):
            assert row['K_' + lev] == d['K_' + lev], (row['series'], lev)
        grouped[row['cell']].append(row)
    decisions = read_csv(results / 'main_decisions.csv')
    assert len(decisions) == 6480 and {r['labour'] for r in decisions} == set(LABOUR)
    counters = {lev: Counter() for lev in LEVELS}
    records = []
    for decision in decisions:
        cell, model, lab = (decision[k] for k in ('cell', 'model', 'labour'))
        theta = float(decision['r'])
        pool = grouped[cell]
        winner = cheapest(pool, 'K_final', model, theta, lab, curves)
        assert winner == decision['winner'], decision
        shares = {r['family']: float(r['coop_share']) for r in pool}
        for lev in LEVELS:
            w = cheapest(pool, 'K_' + lev, model, theta, lab, curves)
            same = w == winner
            counters[lev]['agree'] += same
            counters[lev]['single_carry'] += w is not None and shares[w] <= 0.10 + 1e-12
            counters[lev]['decisions'] += 1
            records.append(dict(level=lev, cell=cell, model=model, r=theta, labour=lab,
                                winner=w, final_winner=winner, same_winner=same,
                                winner_coupled_share=shares.get(w)))
    summary = dict(decisions_per_level=6480, labour_measures=list(LABOUR),
                   scope='K-only repricing; working-time and overtime terms retained from final schedules',
                   levels={lev: dict(counts, agreement_pct=100 * counts['agree'] / counts['decisions'],
                                     single_carry_pct=100 * counts['single_carry'] / counts['decisions'])
                           for lev, counts in counters.items()}, main_winners_reproduced=6480)
    write_json(out / 'search_depth_summary.json', summary)
    write_csv(out / 'search_depth_decisions.csv', records)
    return summary


def slow_handling(results, out, curves):
    lookup = {}
    sources = [(results / 'sensitivity_fleets.csv', 0)]
    sources += [(p, 0) for p in sorted(results.glob('unresolved_scan*_fleets.csv'))]
    sources += [(p, 1) for p in sorted(results.glob('candidates_*_fleets.csv'))]
    for path, index in sources:
        for row in read_csv(path):
            level = row['series'].split('_')[index]
            if level not in SLOW_LEVELS:
                continue
            key = (level, row['cell'], row['family'])
            if row['K_final'] in ('', 'None', None):
                lookup.pop(key, None)
            else:
                lookup[key] = row
    grouped = defaultdict(list)
    for (level, cell, family), row in lookup.items():
        grouped[level, cell].append(row)
    theta_grid = sorted({float(r['r']) for r in read_csv(results / 'main_decisions.csv')})
    decisions = read_csv(results / 'slow_handling_decisions.csv')
    assert len(decisions) == 3600
    for r in decisions:
        theta = next(t for t in theta_grid if round(t, 3) == float(r['r']))
        pool = grouped[r['level'], r['cell']]
        w = cheapest(pool, 'K_final', r['model'], theta, r['labour'], curves)
        assert (w or '') == r['winner'], r
        if w:
            row = next(row for row in pool if row['family'] == w)
            assert math.isclose(float(row['coop_share']), float(r['coop']), abs_tol=1e-12)
    resolved = [r for r in decisions if r['winner']]
    maximum = max(float(r['coop']) for r in resolved)
    max_rows = [r for r in resolved if float(r['coop']) == maximum]
    write_csv(out / 'slow_handling_max_coupling.csv', max_rows)
    return dict(decisions_reproduced=len(decisions), resolved=len(resolved), unresolved=len(decisions) - len(resolved),
                max_coupling_pct=100 * maximum, max_coupling_decisions=len(max_rows),
                all_resolved_couple_at_most_10pct=all(float(r['coop']) <= 0.10 for r in resolved),
                max_coupling_pct_by_level={level: 100 * max(float(r['coop']) for r in resolved if r['level'] == level)
                                           for level in SLOW_LEVELS})


def exact_greedy(results):
    rows = [r for r in read_csv(results / 'exact_kstar.csv') if r['exact'] == 'True']
    assert len(rows) == 56
    counts, missing = Counter(), []
    for r in rows:
        if r['K_greedy'] in ('', 'None', None):
            counts['no_count'] += 1
            missing.append(r)
        else:
            difference = int(r['K_greedy']) - int(r['K_lb'])
            assert difference >= 0
            counts[str(difference)] += 1
    return dict(proven_fleets=len(rows), count_differences=dict(counts), no_count_rows=missing)


def delay_cap(results, curves):
    grid = read_csv(results / 'delay_cap_grid.csv')
    rows = [r for r in grid if r['level'] == '120' and r['labour'] == 'shift_h']
    assert len(rows) == 135
    theta_grid = sorted({float(r['r']) for r in read_csv(results / 'main_decisions.csv')})
    baseline = {(r['cell'], r['model'], r['r'], r['labour']): r for r in grid if r['level'] == 'inf'}
    changes = []
    for r in rows:
        b = baseline[r['cell'], r['model'], r['r'], r['labour']]
        costs = []
        for record in (r, b):
            qs = [int(q) for q in record['fleet'].split()]
            theta = next(t for t in theta_grid if round(t, 3) == float(record['r']))
            computed = theta * sum(price(q, record['model'], curves) for q in qs) + 64 * len(qs)
            assert math.isclose(computed, float(record['cost']), rel_tol=1e-12)
            costs.append(computed)
        change = costs[0] / costs[1] - 1
        assert math.isclose(change, float(r['cost_vs_inf']), abs_tol=1e-12)
        changes.append((change, r, b))
    largest = max(changes, key=lambda x: x[0])
    return dict(cost_pairs_reproduced=len(rows), min_increase_pct=100 * min(x[0] for x in changes),
                max_increase_pct=100 * largest[0], maximum_row=largest[1], no_cap_row=largest[2])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path(__file__).resolve().parent.parent / 'results')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    out = args.out or args.results
    out.mkdir(parents=True, exist_ok=True)
    curves = json.loads((args.results / 'price_curve.json').read_text(encoding='utf-8'))['curves_ex_vat']
    summary = dict(vehicle_time=decomposition(args.results, out), search_depth=search_depth(args.results, out, curves),
                   slow_handling=slow_handling(args.results, out, curves), exact_greedy=exact_greedy(args.results),
                   delay_cap=delay_cap(args.results, curves))
    write_json(out / 'table_checks.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
