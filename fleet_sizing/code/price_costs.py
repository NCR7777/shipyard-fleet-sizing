"""Cost results over the calibrated price models and a continuous r interval.

Capital proxy of fleet X: P_X = sum_k price(Q_k) / price(270) for the fitted price curves
(affine, piecewise; VAT removed), or sum_k (Q_k/270)^alpha for power laws over the 200-550 t
interval alpha in [0.72, 0.96]. Heavy members of the reference mixes are substituted as in the
manuscript (500 t for the Jiang, light-skewed and uniform mass scenarios, 425 t for the Liu
scenario `liu`). r runs over a 400-point log grid on the calibrated interval (main: 2,000 h, VAT removed,
both wage anchors). Inputs: known counts and crew hours of the chosen fleet table (default: the earlier
ten-instance table of the main specification; rerun on the 30-instance counts).

  python price_costs.py [fleets.csv] [liu_mixes.json]
"""
import csv
import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / 'fleet_sizing' / 'results'
SUB = {'jiang': 500, 'lightskew': 500, 'uniform': 500, 'liu': 425}
LAB = ('shift_h', 'crew_veh_h', 'crew_team_h')


def caps(cell, fam, K):
    ms = cell.split('_')[0]
    if fam.startswith('MX'):
        h = int(fam[-1])
        return [SUB.get(ms, 550)] * h + [270] * (K - h)
    if fam.startswith('L'):
        light, rest = fam[1:].split('_H')
        heavy, h = rest.split('x')
        return [int(heavy)] * int(h) + [int(light)] * (K - int(h))
    return [int(fam)] * K


def main(fleets_csv, mixes_json):
    pr = json.loads((RES / 'price_curve.json').read_text(encoding='utf8'))
    cur = pr['curves_ex_vat']
    lo, hi = pr['r_union_main']

    def proxy(model):
        if model[0] == 'power':
            a = model[1]
            return lambda qs: sum((q / 270) ** a for q in qs)
        if model[0] == 'affine':
            f = lambda q: cur['affine']['F'] + cur['affine']['v'] * q
        else:
            c = cur['piecewise']
            f = lambda q: c['b0'] + c['b1'] * q + c['b2'] * max(0, q - c['brk'])
        return lambda qs: sum(f(q) for q in qs) / f(270)

    with open(fleets_csv, encoding='utf-8-sig') as f:
        fl = {(r['cell'], r['family']): dict(K=int(r['K']), shift_h=float(r['shift_h']), crew_veh_h=float(r['crew_veh_h']),
                                             crew_team_h=float(r['crew_team_h'])) for r in csv.DictReader(f)}
    mix = json.loads(Path(mixes_json).read_text(encoding='utf8'))
    rs = np.exp(np.linspace(np.log(lo), np.log(hi), 400))
    models = [('affine',), ('piecewise',)] + [('power', a) for a in (0.72, 0.84, 0.96)]
    out = dict(r_interval=[lo, hi])
    for m in models:
        P = proxy(m)
        name = m[0] if m[0] != 'power' else 'power_%.2f' % m[1]
        liu_ref = {f: (P(caps('liu_short_baseline', f, v['K'])), v) for (c, f), v in fl.items() if c == 'liu_short_baseline'}
        liu_mix = {f: (P(caps('liu_short_baseline', f, v['K'])), dict(v, shift_h=64 * v['K'])) for f, v in mix.items()}
        prem, lead_min, wins = [], [], 0
        for lab in LAB:
            for r in rs:
                cr = min(p * r + v[lab] for p, v in liu_ref.values())
                cm = min(p * r + v[lab] for p, v in liu_mix.values())
                prem.append(cr / min(cr, cm) - 1)
                lead_min.append(cr / cm - 1)
                wins += cm < cr
        big = []
        for (cell, f), v in fl.items():
            tier = '500' if cell.split('_')[0] in ('jiang', 'lightskew') else ('550' if cell.split('_')[0] == 'extraheavy' else None)
            if f != tier:
                continue
            fams = {ff: vv for (cc, ff), vv in fl.items() if cc == cell}
            for r in rs:
                costs = {ff: P(caps(cell, ff, vv['K'])) * r + vv['shift_h'] for ff, vv in fams.items()}
                big.append(costs[tier] / min(costs.values()) - 1)
        out[name] = dict(liu_premium_max=round(100 * max(prem), 1), liu_expanded_min_lead=round(100 * min(lead_min), 1),
                         liu_expanded_wins='%d/%d' % (wins, len(prem)), largest_tier_excess_max=round(100 * max(big), 1))
    RES.mkdir(parents=True, exist_ok=True)
    (RES / 'price_costs.json').write_text(json.dumps(out, indent=1) + '\n', encoding='utf8')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    a = sys.argv[1:]
    main(a[0] if a else ROOT / 'earlier_study/results/cost_fleets_tmax120/known_cost_fleets.csv',
         a[1] if len(a) > 1 else ROOT / 'earlier_study/results/liu_mixes.json')
