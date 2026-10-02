"""Structural screen: can the service target be met at ANY count <= 40 (the base instances hold 40 start positions)?

For every series and day, a lower bound on each block's completion time that holds for every schedule and count:
  arrival_i >= A_i = min( min_k tauE_start[k][i],  min_{j != i} (r_j + D_j + tauE[j][i]) )
  (a transporter reaches block i either from a start position or after completing some other block j,
   which cannot finish before r_j + D_j)
  c_i >= LB_i = max(r_i, A_i) + D_i + delta_i * [no single transporter of the family can lift block i]
Block i is surely late if LB_i > d_i and surely beyond the cap if LB_i > d_i + T_max.
Verdict per series: 'unattainable' if some block is surely beyond the cap on some day (no capped schedule exists),
or if the surely-late blocks over the 30 days exceed the allowance (n_total - ceil(0.95 n_total)); else 'open'
(the screen cannot decide; the scan has to). 'structural' if some block cannot be lifted by any legal team.

  python structural_screen.py <study> [series-prefix ...]     -> results/<study>_precheck.csv
  python structural_screen.py selftest
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
sys.path.insert(0, str(STUDY_ROOT / 'code'))
sys.path.insert(0, str(STUDY_ROOT / 'solver' / 'common'))
KMAX = 40


def bounds(d, caps):
    from core import Inst
    e = dict(d, vehicles=[dict(d['vehicles'][k], cap=c) for k, c in enumerate(caps)], tauE_start=d['tauE_start'][:len(caps)])
    e['meta'] = dict(d['meta'], objective_mode='cap', crew_team=None)
    inst = Inst(e)
    if any(not inst.teams(i, 'flex') for i in range(inst.n)):
        return None
    qmax = max(caps)
    out = []
    for i in range(inst.n):
        a = min(inst.tE0[k][i] for k in range(inst.K))
        for j in range(inst.n):
            if j != i:
                a = min(a, inst.rel[j] + inst.D[j] + inst.tE[j][i])
        lb = max(inst.rel[i], a) + inst.D[i] + (inst.dl[i] if inst.mass[i] > qmax else 0)
        out.append(lb - inst.due[i])
    return out


def screen(study, sp, tmax):
    import fleet_scan
    seeds = sp.get('seeds', fleet_scan.SEEDS)
    caps = fleet_scan.caps_of(sp['family'], KMAX)
    late = over = n = 0
    worst = -math.inf
    for s in seeds:
        d = json.loads((study / sp['base'][str(s)]).read_text(encoding='utf8'))
        lbs = bounds(d, caps)
        if lbs is None:
            return dict(series=sp['name'], verdict='structural', surely_late=None, surely_over=None, allowance=None, worst_delay_lb_min=None)
        n += len(lbs)
        late += sum(x > 0 for x in lbs)
        over += sum(x > tmax for x in lbs)
        worst = max(worst, max(lbs))
    allow = n - math.ceil(0.95 * n - 1e-9)
    verdict = 'unattainable' if over > 0 or late > allow else 'open'
    return dict(series=sp['name'], verdict=verdict, surely_late=late, surely_over=over, allowance=allow,
                worst_delay_lb_min=round(worst / 60, 1))


def main(study_name, prefixes):
    study = STUDY_ROOT / study_name
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    rows = [screen(study, sp, sp['tmax_s'] or math.inf) for sp in specs if not prefixes or sp['name'].startswith(tuple(prefixes))]
    p = STUDY_ROOT / 'results' / ('%s_precheck.csv' % study_name)
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)


def selftest():
    n = 4
    d = dict(name='t', tasks=[dict(id=str(i), mass=100, release=0, due=3600 if i else 600, load=300, unload=300, tauL=600, turns=0)
                              for i in range(n)],
             vehicles=[{'id': k} for k in range(KMAX)], tauE_start=[[300] * n for _ in range(KMAX)],
             tauE=[[0 if i == j else 200 for j in range(n)] for i in range(n)], meta=dict(delta_s=600, crew=4, max_team=3))
    lbs = bounds(d, [270] * KMAX)
    assert lbs[0] == 300 + 1200 - 600 and all(x < 0 for x in lbs[1:]), lbs       # block 0: due 600 s, LB 1500 s
    d['tasks'][1]['mass'] = 400
    lbs2 = bounds(d, [270] * KMAX)                                                  # coupled: + delta
    assert lbs2[1] == lbs[1] + 600, (lbs, lbs2)
    d['tasks'][2]['mass'] = 900
    assert bounds(d, [270] * KMAX) is None                                          # three 270 t units cannot lift 900 t
    print('structural_screen self-test passed')


if __name__ == '__main__':
    if sys.argv[1] == 'selftest':
        selftest()
    else:
        main(sys.argv[1], sys.argv[2:])
