"""Greedy search-intensity level: one chronological greedy construction
(baselines.greedy_append of the solver package `solver_reference`, flexible coupling, lambda = 0; deterministic) per
(series, K, instance) on the main-study base instances (directory `main`) with the main-study fleets and cap.
Counts are scanned upwards from the structural minimum until the series qualifies under the rule of
fleet_scan.py (every instance has a schedule
within the cap at some count <= K; on-time total >= 2,765), or up to K_S + 10 (then "above the
scan"). Output: results/greedy_level.json {series: {"K_greedy": k or null, "runs": {K: [per seed]}}}.

  python greedy_level.py [study=main] [workers=4]
"""
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
SOLVER = STUDY_ROOT / 'solver_reference'
sys.path.insert(0, str(HERE))
import fleet_scan                                              # noqa: E402

SEEDS = fleet_scan.SEEDS
NEED = math.ceil(0.95 * 97 * len(SEEDS) - 1e-9)


def scan(args):
    study, sp = args
    for sub in ('common', 'search'):
        if str(SOLVER / sub) not in sys.path:
            sys.path.insert(0, str(SOLVER / sub))
    from core import Inst, evaluate
    from baselines import greedy_append
    bases = {s: json.loads((study / sp['base'][str(s)]).read_text(encoding='utf8')) for s in SEEDS}
    runs, best, kq, t0 = {}, {}, None, time.time()
    for K in range(sp['K_min'], sp['K_start'] + 11):
        out = []
        for s in SEEDS:
            d = json.loads(json.dumps(bases[s]))
            d['vehicles'] = [dict(d['vehicles'][k], cap=c) for k, c in enumerate(fleet_scan.caps_of(sp['family'], K))]
            d['tauE_start'] = d['tauE_start'][:K]
            d['meta'].update(objective_mode=sp['objective'], tmax_s=sp['tmax_s'], crew_team=None)
            inst = Inst(d)
            if any(not inst.teams(i, 'flex') for i in range(inst.n)):
                out = None
                break
            g = greedy_append(inst, 0, 'flex')
            ev = evaluate(inst, g['order'], g['team'], 0, detail=True)
            late = [ev['comp'][i] - inst.due[i] for i in range(inst.n)]
            r = dict(seed=s, on=sum(x <= 0 for x in late), over=sum(x > sp['tmax_s'] for x in late),
                     crew_veh_h=ev['crew_s'] / 3600)
            out.append(r)
            if r['over'] == 0:                       # lower counts embed into higher ones
                best[s] = max(best.get(s, -1), r['on'])
        runs[K] = out
        if len(best) == len(SEEDS) and sum(best.values()) >= NEED:
            kq = K
            break
    return sp['name'], dict(K_greedy=kq, K_scanned=max(runs), runs=runs, wall_s=time.time() - t0)


def selfcheck():
    """Embedding rule: once a count qualifies, larger counts are never scanned; a fleet whose
    single-count scan qualifies at K_min returns K_min."""
    sp = json.loads((STUDY_ROOT / 'main' / 'series.json').read_text(encoding='utf8'))
    name, r = scan((STUDY_ROOT / 'main', dict(sp[0], K_start=sp[0]['K_min'])))
    assert r['K_greedy'] is None or r['K_greedy'] == max(r['runs'])
    print('greedy-level self-check', name, r['K_greedy'], sorted(r['runs']))


if __name__ == '__main__':
    import psutil
    if sys.argv[1:2] == ['selfcheck']:
        selfcheck()
        sys.exit()
    study = STUDY_ROOT / (sys.argv[1] if len(sys.argv) > 1 else 'main')
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    out_p = STUDY_ROOT / 'results' / 'greedy_level.json'
    res = json.loads(out_p.read_text(encoding='utf8')) if out_p.exists() else {}
    todo = [(study, sp) for sp in specs if sp['name'] not in res]
    with ProcessPoolExecutor(workers) as pool:
        for n, (name, r) in enumerate(pool.map(scan, todo), 1):
            res[name] = r
            if n % 8 == 0 or n == len(todo):
                tmp = out_p.with_suffix('.tmp')
                tmp.write_text(json.dumps(res) + '\n', encoding='utf8')
                tmp.replace(out_p)
            (STUDY_ROOT / 'results' / 'greedy_level.progress').write_text('%d / %d\n' % (len(res), len(specs)), encoding='utf8')
