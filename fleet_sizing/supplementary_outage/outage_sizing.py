"""One-unit-outage (N-1) sizing and pricing from the main results (no new runs).

A fleet X is N-1 robust at count K if it still meets the service specification (pooled 95 %, 120-min cap) with any one
transporter out of service on every day. Removing a unit leaves
  - a light (or, for homogeneous fleets, any) unit out: X at K - 1          -> qualifies iff K - 1 >= K*_X
  - a heavy unit out (mixes only): X- at K - 1, X- = X with one heavy unit fewer
    (MX2 -> MX1 -> 270, L<l>_H<q>x h -> x(h-1) -> <l>)                  -> qualifies iff K - 1 >= K*_{X-}
(counts are embedded: a fleet that qualifies at K qualifies at every larger K), so
  K_N1(X) = max(K*_X, K*_{X-}) + 1.
The start positions differ by one place from the scanned fleet of X- (immaterial for the instance).
Each fleet is priced at K_N1 with the usual pricing knapsack (one stored run per day, count <= K_N1, no block over the
cap, minimum per-transporter crew hours at >= 95 % on time) on the main grid (5 price curves x 9 r x 4 labour measures).
Coupled share of a fleet: blocks coupled in those nominal schedules (all units available).

Value of the coupling option (outside the extra-heavy scenario, i.e. where some tier carries every block): the extra
cost of the cheapest fleet when coupling is not available at all, nominally and under N-1 sizing; the difference is
its insurance value.
Admissible without coupling: nominally, covering homogeneous tiers and mixes with a covering heavy tier; under N-1,
covering homogeneous tiers and mixes with >= 2 covering heavy units (the fleet must lift every block with any unit out).
  upper bound: cheapest covering homogeneous tier (exact: such fleets cannot form coupled teams)
  lower bound: cheapest admissible fleet priced with the coupling-allowed counts (no-coupling counts can only be higher)

Inputs : `results/runs_compact/main.csv`, `delay_cap.csv` (rows `T120_*` of the delay-cap study), `main_fleets.csv`,
         `delay_cap_fleets.csv`, `price_curve.json`
Outputs: results/outage_sizing_fleets.csv, outage_sizing_decisions.csv, outage_sizing_summary.json
  python outage_sizing.py          # about two minutes
"""
import csv
import json
import math
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(STUDY_ROOT / 'code'))
import cost_decisions as RC                                   # noqa: E402
import analyse_study as A                                   # noqa: E402

SEEDS = list(range(101, 131))
NEED = math.ceil(0.95 * 97 * 30 - 1e-9)
CR = 0.10


def minus_heavy(f):
    if f.startswith('MX'):
        h = int(f[-1])
        return 'MX%d' % (h - 1) if h > 1 else '270'
    if f.startswith('L'):
        light, rest = f[1:].split('_H')
        q, h = rest.split('x')
        return 'L%s_H%sx%d' % (light, q, int(h) - 1) if int(h) > 1 else light
    return f


def heavy_count(f):
    return int(f[-1]) if f.startswith('MX') else int(f.split('x')[1]) if f.startswith('L') else 0


def load_runs():
    runs = {}
    for name, keep in (('main.csv', lambda s: True), ('delay_cap.csv', lambda s: s.startswith('T120_'))):
        with open(RES / 'runs_compact' / name, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if not keep(r['series']):
                    continue
                key = (r['cell'], r['family'])
                v = None if r['status'] != 'OK' else dict(
                    on=int(r['on_time']), over=int(r['n_over']), crew_veh=float(r['crew_veh_h']), crew_team=float(r['crew_team_h']),
                    after=float(r['after_h']), coop=int(r['n_coop']))
                runs.setdefault(key, {})[int(r['K']), int(r['seed']), int(r['j'])] = v
    return runs


def kstar():
    out = {}
    for name, keep in (('main_fleets.csv', lambda s: True), ('delay_cap_fleets.csv', lambda s: s.startswith('T120_'))):
        for r in csv.DictReader(open(RES / name, encoding='utf-8-sig')):
            if keep(r['series']) and r['K_final'] not in ('', 'None'):
                out[r['cell'], r['family']] = int(float(r['K_final']))
    return out


def priced_row(runs, K):
    ch = A.knapsack(runs, K, NEED, SEEDS)
    n = len(SEEDS)
    return dict(K=K, crew_veh_h=sum(x[1] for x in ch) / n, crew_team_h=sum(x[2] for x in ch) / n, after_h=sum(x[3] for x in ch) / n,
                coop_share=sum(x[4] for x in ch) / (97 * n))


def main():
    runs, ks = load_runs(), kstar()
    maxmass = {}
    with open(RES / 'runs_compact' / 'tasks_R4.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            maxmass[r['cell']] = max(maxmass.get(r['cell'], 0), float(r['mass_t']))
    fleets, nom, n1 = [], {}, {}
    for (cell, fam), k in sorted(ks.items()):
        fm = minus_heavy(fam)
        km = ks.get((cell, fm))
        kn1 = None if km is None else max(k, km) + 1
        sim_heavy = 550 if fam.startswith('MX') else int(fam.split('_H')[1].split('x')[0]) if fam.startswith('L') else int(fam)
        h = heavy_count(fam)
        covering_after_outage = (sim_heavy >= maxmass[cell]) and (h == 0 or h >= 2)
        nom[cell, fam] = priced_row(runs[cell, fam], k)
        if kn1 is not None:
            n1[cell, fam] = priced_row(runs[cell, fam], kn1)
        fleets.append(dict(cell=cell, family=fam, K_star=k, minus_heavy=fm if fm != fam else '', K_star_minus=km if fm != fam else '',
                           K_N1=kn1, premium_units=(kn1 - k) if kn1 else None, admissible_without_coupling=covering_after_outage,
                           homogeneous_covering=(h == 0 and not fam.startswith('L') and int(fam) >= maxmass[cell]),
                           covering_mix=(h >= 1 and sim_heavy >= maxmass[cell]),
                           coop_nominal=nom[cell, fam]['coop_share'], coop_at_K_N1=n1[cell, fam]['coop_share'] if kn1 else None))
    info = {(r['cell'], r['family']): r for r in fleets}
    rows = []
    for cell in sorted({c for c, _ in ks}):
        fams = sorted(f for c, f in ks if c == cell)
        for m in RC.MAIN_MODELS:
            P = RC.proxy(m)
            for r in RC.main_r():
                for lab in RC.LAB4:
                    def cost(tab, f):
                        v = tab[cell, f]
                        return r * P(RC.caps(cell, f, v['K'])) + RC.labour(v, lab, v['K'])
                    cn = {f: cost(nom, f) for f in fams}
                    c1 = {f: cost(n1, f) for f in fams if (cell, f) in n1}
                    wn, w1 = min(cn, key=cn.get), min(c1, key=c1.get)
                    hom = [f for f in c1 if info[cell, f]['homogeneous_covering']]
                    adm1 = [f for f in c1 if info[cell, f]['admissible_without_coupling']]
                    adm0 = [f for f in cn if info[cell, f]['homogeneous_covering'] or info[cell, f]['covering_mix']]
                    gap = cell.startswith('extraheavy')            # some blocks exceed every tier: coupling is necessary anyway
                    rows.append(dict(cell=cell, model=RC.mname(m), r=round(r, 6), labour=lab, winner_nominal=wn,
                                     winner_N1=w1, K_N1=n1[cell, w1]['K'], coop_N1=n1[cell, w1]['coop_share'],
                                     N1_winner_one_heavy_mix=heavy_count(w1) == 1,
                                     premium_N1=c1[w1] / cn[wn] - 1,
                                     option_nominal_upper=None if gap or not hom else min(cn[f] for f in hom) / cn[wn] - 1,
                                     option_nominal_lower=None if gap or not adm0 else max(0.0, min(cn[f] for f in adm0) / cn[wn] - 1),
                                     option_N1_upper=None if gap or not hom else min(c1[f] for f in hom) / c1[w1] - 1,
                                     option_N1_lower=None if gap or not adm1 else max(0.0, min(c1[f] for f in adm1) / c1[w1] - 1)))
    ex = [x for x in rows if not x['cell'].startswith('extraheavy')]
    q = lambda v: dict(median=st.median(v), p90=sorted(v)[int(0.9 * (len(v) - 1))], max=max(v)) if v else None
    summ = dict(settings=len(rows), fleets=len(fleets), fleets_without_N1_count=sum(r['K_N1'] is None for r in fleets),
                single_carry_N1=sum(x['coop_N1'] <= CR for x in rows) / len(rows),
                single_carry_N1_outside_extraheavy=sum(x['coop_N1'] <= CR for x in ex) / len(ex),
                same_winner_as_nominal=sum(x['winner_N1'] == x['winner_nominal'] for x in rows) / len(rows),
                N1_winner_one_heavy_mix_outside_extraheavy=sum(x['N1_winner_one_heavy_mix'] for x in ex) / len(ex),
                nominal_winner_one_heavy_mix_outside_extraheavy=sum(heavy_count(x['winner_nominal']) == 1 for x in ex) / len(ex),
                premium_N1=q([x['premium_N1'] for x in rows]),
                option_value_nominal_upper=q([x['option_nominal_upper'] for x in ex if x['option_nominal_upper'] is not None]),
                option_value_nominal_lower=q([x['option_nominal_lower'] for x in ex if x['option_nominal_lower'] is not None]),
                option_value_N1_upper=q([x['option_N1_upper'] for x in ex if x['option_N1_upper'] is not None]),
                option_value_N1_lower=q([x['option_N1_lower'] for x in ex if x['option_N1_lower'] is not None]),
                option_N1_upper_zero_share=sum(x['option_N1_upper'] == 0 for x in ex if x['option_N1_upper'] is not None) /
                max(1, sum(x['option_N1_upper'] is not None for x in ex)),
                option_nominal_upper_zero_share=sum(x['option_nominal_upper'] == 0 for x in ex if x['option_nominal_upper'] is not None) /
                max(1, sum(x['option_nominal_upper'] is not None for x in ex)),
                winners_N1=dict(Counter(x['winner_N1'] for x in rows).most_common(12)),
                extra_units_of_N1_winner=dict(Counter(x['K_N1'] - info[x['cell'], x['winner_N1']]['K_star'] for x in rows)),
                by_labour={l: dict(single_carry_N1=sum(x['coop_N1'] <= CR for x in rows if x['labour'] == l) / sum(x['labour'] == l for x in rows),
                                   same_winner=sum(x['winner_N1'] == x['winner_nominal'] for x in rows if x['labour'] == l) /
                                   sum(x['labour'] == l for x in rows)) for l in RC.LAB4})
    for name, tab in (('outage_sizing_fleets.csv', fleets), ('outage_sizing_decisions.csv', rows)):
        with open(RES / name, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(tab[0]))
            w.writeheader()
            w.writerows(tab)
    (RES / 'outage_sizing_summary.json').write_text(json.dumps(summ, indent=1) + '\n', encoding='utf8')
    print(json.dumps(summ, indent=1))


if __name__ == '__main__':
    main()
