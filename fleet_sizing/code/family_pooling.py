"""Pooling across fleet families: counts pooled across fleet types, main-study runs only (directory `main`).

Within one cell (identical instances), every main-study run of every series is mapped to each target series:
transporter indices are kept, each team is replaced by a smallest subset that is a minimal feasible
team of the target fleet (Proposition 1), and the result is replayed on the target's own instance at
the source count (idle transporters above it). Per seed and count, the options are all mapped
schedules with no block beyond the cap at counts <= K. The pooled count is the smallest K at which
every instance has an option and the best options reach the on-time target; pricing options feed the
same knapsack as the main counts. Checks: mapping a series' own run is the identity and reproduces
its stored outcome; a pooled count never exceeds the own-series count.

  python family_pooling.py [workers]   -> results/family_pooling.csv, results/family_pooling.json
"""
import csv
import itertools
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
SOLVER = STUDY_ROOT / 'solver_reference'
sys.path.insert(0, str(HERE))
import fleet_scan                                              # noqa: E402
import analyse_study as A                                    # noqa: E402

STUDY = STUDY_ROOT / 'main'


def cell_job(cell):
    for sub in ('common', 'search'):
        if str(SOLVER / sub) not in sys.path:
            sys.path.insert(0, str(SOLVER / sub))
    from core import Inst, evaluate
    specs = [sp for sp in json.loads((STUDY / 'series.json').read_text(encoding='utf8')) if sp['cell'] == cell]
    own = {sp['name']: A.load(STUDY, sp) for sp in specs}
    kstar = {}
    need = math.ceil(0.95 * 97 * len(A.SEEDS) - 1e-9)
    for sp in specs:
        runs = own[sp['name']]
        comp = [k for k in sorted({k for (k, s, j) in runs}) if all((k, s, 0) in runs for s in A.SEEDS)]
        q = [k for k in comp if A.qualifies(runs, k, 'final', need)]
        kstar[sp['name']] = min(q) if q else None
    src = []
    for sp in specs:
        for p in (STUDY / 'runs' / sp['name']).glob('K*_s*_j*.json'):
            r = json.loads(p.read_text(encoding='utf8'))
            if r['status'] == 'OK' and r['n_over'] == 0:
                src.append((sp['name'], r['job']['K'], r['job']['seed'], r['job']['j'], r['order'], r['team'], r['on_time']))
    cache = {}

    def inst(sp, K, s):
        if (sp['name'], K, s) not in cache:
            d = json.loads((STUDY / sp['base'][str(s)]).read_text(encoding='utf8'))
            d['vehicles'] = [dict(d['vehicles'][q], cap=c) for q, c in enumerate(fleet_scan.caps_of(sp['family'], K))]
            d['tauE_start'] = d['tauE_start'][:K]
            d['meta'].update(objective_mode=sp['objective'], tmax_s=sp['tmax_s'], crew_team=None)
            cache[sp['name'], K, s] = Inst(d)
        return cache[sp['name'], K, s]

    out = {}
    for sp in specs:
        ks = kstar[sp['name']]
        if ks is None:
            out[sp['name']] = dict(K_own=None, K_pooled=None)
            continue
        opts = {}                                     # (K, seed) -> [(on, crew_veh, crew_team, source series)]
        for name, K, s, j, order, team, on0 in src:
            if K > ks or K < sp['K_min']:
                continue
            I = inst(sp, K, s)
            mt = {}
            for i_str, S in team.items():
                allowed = set(map(tuple, I.teams(int(i_str), 'flex')))
                pick = next((sub for size in range(1, len(S) + 1) for sub in itertools.combinations(sorted(S), size)
                             if sub in allowed), None)
                if pick is None:
                    break
                mt[int(i_str)] = pick
            if len(mt) < I.n:
                continue
            ev = evaluate(I, order, mt, 0, detail=True)
            late = [ev['comp'][i] - I.due[i] for i in range(I.n)]
            on = sum(x <= 0 for x in late)
            if name == sp['name']:
                assert on == on0 and all(tuple(v) == mt[int(i)] for i, v in team.items()), (name, K, s, j)
            if max(late) > sp['tmax_s']:
                continue
            d2 = json.loads(json.dumps(I.raw))
            d2['meta']['crew_team'] = {1: 4, 2: 4, 3: 4}
            ct = evaluate(Inst(d2), order, mt, 0)['crew_s']
            opts.setdefault((K, s), []).append((on, ev['crew_s'] / 3600, ct / 3600, name))
        runs = {}                                     # analyse_study-compatible: key (K, seed, q)
        for (K, s), lst in opts.items():
            for q, (on, cv, ct, name) in enumerate(lst):
                runs[K, s, q] = dict(on=on, over=0, crew_veh=cv, crew_team=ct, after=0.0, coop=0, src=name)
        kp = next((K for K in range(sp['K_min'], ks + 1) if A.qualifies(runs, K, 'final', need)), None)
        assert kp is not None and kp <= ks, (sp['name'], kp, ks)
        ch = A.knapsack(runs, kp, need)
        srcs = sorted({runs[x[5]]['src'] for x in ch})
        out[sp['name']] = dict(cell=cell, family=sp['family'], K_own=ks, K_pooled=kp,
                               crew_veh_h=sum(x[1] for x in ch) / len(A.SEEDS), crew_team_h=sum(x[2] for x in ch) / len(A.SEEDS),
                               n_sources=len(srcs), sources=srcs)
    return out


if __name__ == '__main__':
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    cells = sorted({sp['cell'] for sp in json.loads((STUDY / 'series.json').read_text(encoding='utf8'))})
    res = {}
    with ProcessPoolExecutor(workers) as pool:
        for part in pool.map(cell_job, cells):
            res.update(part)
    (STUDY_ROOT / 'results' / 'family_pooling.json').write_text(json.dumps(res, indent=1) + '\n', encoding='utf8')
    rows = [dict(series=k, **{f: v.get(f) for f in ('cell', 'family', 'K_own', 'K_pooled', 'crew_veh_h', 'crew_team_h',
                                                     'n_sources')}) for k, v in res.items()]
    with (STUDY_ROOT / 'results' / 'family_pooling.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(dict(series=len(res), lower=sum(1 for v in res.values() if v.get('K_pooled') and v['K_pooled'] < v['K_own']))))
