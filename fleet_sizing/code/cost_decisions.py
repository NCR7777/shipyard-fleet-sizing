"""Cost decisions (calibrated price curves, after-shift labour, search dependence of a decision).

Decision = (cell, price model, r, labour measure) -> cheapest fleet type among the cell's series at
their counts K. Cost C_X = r * P_X + L_X with P_X = sum_k p(Q_k)/p(270); heavy members of the
reference mixes are substituted as in the manuscript (500 t for the Jiang, light-skewed and uniform mass
scenarios, 425 t for the Liu scenario).
  main grid : 5 price models (affine [main], piecewise, power 0.72/0.84/0.96) x 9 r (5.1-30, log)
              x 4 labour measures (shift, per-transporter crew, per-team crew, shift + 1.5 x 4 x after-shift h)
  old grid  : power 0.6/0.8/1.0 x r in {5,10,20,40,85} x 3 labour measures (full-grid statements only)
Search-dependence status: "certain" if every losing type X either cannot lose a transporter (K_X - 1 below the
family's scan floor, or K_X - 1 proven infeasible) or is still not cheaper than the winner when
priced at K_X - 1 (shift labour 64 (K_X - 1), operating labour as at K_X); otherwise "search-dependent".

  python cost_decisions.py <fleets.csv> <out_prefix> [proven.json]
  python cost_decisions.py selfcheck        # the earlier ten-instance inputs must reproduce their reference winners
"""
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RES = ROOT / 'fleet_sizing' / 'results'
SUB = {'jiang': 500, 'lightskew': 500, 'uniform': 500, 'liu': 425}
MAIN_MODELS = (('affine',), ('piecewise',), ('power', 0.72), ('power', 0.84), ('power', 0.96))
OLD_MODELS = (('power', 0.6), ('power', 0.8), ('power', 1.0))
LAB3 = ('shift_h', 'crew_veh_h', 'crew_team_h')
LAB4 = LAB3 + ('shift_ot_h',)
OMEGA, OT = 4, 1.5


def main_r():
    lo, hi = json.loads((RES / 'price_curve.json').read_text(encoding='utf8'))['r_union_main']
    return tuple(float(x) for x in np.exp(np.linspace(math.log(lo), math.log(hi), 9)))


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


def floor_of(fam):
    """Smallest count that still belongs to the family (scan floor of fleet_scan.kmin_of)."""
    if fam.startswith('L'):
        return int(fam.split('x')[-1]) + 1
    if fam.startswith('MX'):
        return int(fam[-1]) + 1
    return 3


def proxy(model):
    if model[0] == 'power':
        a = model[1]
        return lambda qs: sum((q / 270) ** a for q in qs)
    cur = json.loads((RES / 'price_curve.json').read_text(encoding='utf8'))['curves_ex_vat']
    if model[0] == 'affine':
        f = lambda q: cur['affine']['F'] + cur['affine']['v'] * q
    else:
        c = cur['piecewise']
        f = lambda q: c['b0'] + c['b1'] * q + c['b2'] * max(0, q - c['brk'])
    return lambda qs: sum(f(q) for q in qs) / f(270)


def mname(m):
    return m[0] if m[0] != 'power' else 'power_%.2f' % m[1]


def labour(v, lab, K):
    if lab == 'shift_h':
        return 64 * K
    if lab == 'shift_ot_h':
        return 64 * K + OT * OMEGA * v['after_h']
    return v[lab]


def load(fleets_csv):
    with open(fleets_csv, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    fl = {}
    for r in rows:
        k = r.get('K_final', r.get('K'))
        if k in (None, '', 'None'):
            continue
        fl[r['cell'], r['family']] = dict(K=int(k), crew_veh_h=float(r['crew_veh_h']), crew_team_h=float(r['crew_team_h']),
                                          after_h=float(r['after_h']) if r.get('after_h') not in (None, '') else None)
    return fl


def decisions(fl, models, rs, labs, proven=frozenset()):
    out = []
    for cell in sorted({c for c, _ in fl}):
        fams = {f: v for (c, f), v in fl.items() if c == cell}
        for m in models:
            P = proxy(m)
            cap = {f: P(caps(cell, f, v['K'])) for f, v in fams.items()}
            capm = {f: P(caps(cell, f, v['K'] - 1)) for f, v in fams.items()}
            for r in rs:
                for lab in labs:
                    cost = {f: r * cap[f] + labour(v, lab, v['K']) for f, v in fams.items()}
                    w = min(cost, key=cost.get)
                    risky = [f for f, v in fams.items() if f != w and v['K'] - 1 >= floor_of(f) and (cell, f) not in proven
                             and r * capm[f] + labour(v, lab, v['K'] - 1) < cost[w]]
                    srt = sorted(cost.values())
                    out.append(dict(cell=cell, model=mname(m), r=r, labour=lab, winner=w, margin=srt[1] / srt[0] - 1,
                                    status='search-dependent' if risky else 'certain', flip_by=' '.join(risky)))
    return out


def write(rows, path):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def selfcheck():
    rows = decisions(load(RES / 'main_fleets.csv'), MAIN_MODELS, main_r(), LAB4)
    with open(RES / 'main_decisions.csv', encoding='utf-8-sig') as handle:
        reference = list(csv.DictReader(handle))
    key = lambda r: (r['cell'], r['model'], round(float(r['r']), 8), r['labour'])
    lookup = {key(r): r for r in reference}
    assert len(rows) == len(lookup) == 6480
    assert all(r['winner'] == lookup[key(r)]['winner'] and
               abs(r['margin'] - float(lookup[key(r)]['margin'])) < 1e-12 for r in rows)
    print('self-check: all 6,480 main winners and margins reproduced')


if __name__ == '__main__':
    if sys.argv[1] == 'selfcheck':
        selfcheck()
        sys.exit()
    fl = load(sys.argv[1])
    prefix = sys.argv[2]
    proven = frozenset(tuple(x) for x in json.loads(Path(sys.argv[3]).read_text(encoding='utf8'))) if len(sys.argv) > 3 else frozenset()
    main_rows = decisions(fl, MAIN_MODELS, main_r(), LAB4 if all(v['after_h'] is not None for v in fl.values()) else LAB3, proven)
    write(main_rows, RES / ('%s_decisions.csv' % prefix))
    summ = {}
    for name, rows in (('main', main_rows),):
        summ[name] = dict(decisions=len(rows), search_dependent=sum(x['status'] == 'search-dependent' for x in rows),
                          min_margin_pct=round(100 * min(x['margin'] for x in rows), 2))
    shift = {(x['cell'], x['model'], x['r']): x['winner'] for x in main_rows if x['labour'] == 'shift_h'}
    ot = {(x['cell'], x['model'], x['r']): x['winner'] for x in main_rows if x['labour'] == 'shift_ot_h'}
    if ot:
        summ['after_shift_changed'] = sum(shift[k] != ot[k] for k in ot)
        summ['after_shift_of'] = len(ot)
    (RES / ('%s_decisions_summary.json' % prefix)).write_text(json.dumps(summ, indent=1) + '\n', encoding='utf8')
    print(json.dumps(summ))
