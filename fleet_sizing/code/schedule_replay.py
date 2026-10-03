"""Replays of the pricing-selected schedules.

For every series with a known count K*: the multiple-choice knapsack of analyse_study picks one run per
instance (any j, any count <= K*, within the cap); each picked schedule is replayed with core.evaluate of
the solver package (`solver_reference`) (per-transporter order and teams kept, earliest start) and reports
  - shift-hard on-time (completion after the shift end also counts as late) and whether the target
    is still met;
  - after-shift transporter hours (per instance, averaged) and the largest daily after-shift share of
    available transporter time (K* x shift);
  - handling variability: 20 scenarios per schedule, loading and unloading x U(0.5, 1.5) with
    random numbers from (instance seed, scenario), shared across fleets; mean on-time, share of
    (instance, scenario) pairs with a block later than the cap, maximum delay.
Shift end: 16 h for the main case, 600 min for the second case (directory `second_case`).

  python schedule_replay.py <study> [workers]     -> results/<study>_replay.json
"""
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
SOLVER = STUDY_ROOT / 'solver_reference'
sys.path.insert(0, str(HERE))
import fleet_scan_studies                                          # noqa: E402,F401  (ADD families for the second case)
import fleet_scan                                              # noqa: E402
import analyse_study as A                                    # noqa: E402

N_SCEN, SPREAD = 20, 0.5


def chosen(study, sp):
    runs = A.load(study, sp)
    seeds = sp.get('seeds', A.SEEDS)
    ntot = sp.get('n_total', 97 * len(seeds))
    need = math.ceil(0.95 * ntot - 1e-9)
    complete = [k for k in sorted({k for (k, s, j) in runs}) if all((k, s, 0) in runs for s in seeds)]
    q = [k for k in complete if A.qualifies(runs, k, 'final', need, seeds)]
    if not q:
        return None, need, ntot, []
    K = min(q)
    return K, need, ntot, [x[5] for x in A.knapsack(runs, K, need, seeds)]


def instance(study, sp, k, s):
    from core import Inst
    d = json.loads((study / sp['base'][str(s)]).read_text(encoding='utf8'))
    d['vehicles'] = [dict(d['vehicles'][q], cap=c) for q, c in enumerate(fleet_scan.caps_of(sp['family'], k))]
    d['tauE_start'] = d['tauE_start'][:k]
    d['meta'].update(objective_mode=sp['objective'], tmax_s=sp['tmax_s'], crew_team=None)
    return Inst(d)


def metrics(inst, order, team, tmax, shift_end):
    from core import evaluate
    ev = evaluate(inst, order, team, 0, detail=True)
    late = [ev['comp'][i] - inst.due[i] for i in range(inst.n)]
    last = [max((ev['comp'][i] for i in q), default=0) for q in ev['seqs']]
    return dict(on=sum(x <= 0 for x in late), over=sum(x > tmax for x in late), max_tard=max(0, max(late)),
                on_shift=sum(late[i] <= 0 and ev['comp'][i] <= shift_end for i in range(inst.n)),
                after_s=sum(max(0, c - shift_end) for c in last))


def replay(args):
    for sub in ('common', 'search'):
        if str(SOLVER / sub) not in sys.path:
            sys.path.insert(0, str(SOLVER / sub))
    from core import scenario_inst
    study, sp, shift_end = args
    K, need, ntot, keys = chosen(study, sp)
    if K is None:
        return sp['name'], None
    tmax = sp['tmax_s'] or float('inf')
    nom, pert, dag = [], [], 0.0
    for k, s, j in keys:
        r = json.loads((study / 'runs' / sp['name'] / ('K%d_s%d_j%d.json' % (k, s, j))).read_text(encoding='utf8'))
        order, team = r['order'], {int(i): tuple(v) for i, v in r['team'].items()}
        inst = instance(study, sp, k, s)
        m = metrics(inst, order, team, tmax, shift_end)
        assert m['on'] == r['on_time'] and m['over'] == r['n_over'], (sp['name'], k, s, j)
        nom.append(m)
        dag = max(dag, m['after_s'] / (K * shift_end))
        for q in range(N_SCEN):
            rng = random.Random(s * 1000 + q)
            L = [x * rng.uniform(1 - SPREAD, 1 + SPREAD) for x in inst.load]
            U = [x * rng.uniform(1 - SPREAD, 1 + SPREAD) for x in inst.unload]
            pert.append(metrics(scenario_inst(inst, L, U), order, team, tmax, shift_end))
    n = len(nom)
    return sp['name'], dict(
        K=K, need=need, n_total=ntot, on=sum(m['on'] for m in nom), on_shift=sum(m['on_shift'] for m in nom),
        meets_shift_hard=sum(m['on_shift'] for m in nom) >= need, after_h=sum(m['after_s'] for m in nom) / 3600 / n,
        after_days=sum(m['after_s'] > 0 for m in nom), max_after_share=dag,
        replay_on_nominal=sum(m['on'] for m in nom) / ntot, replay_on_pert=sum(m['on'] for m in pert) / (N_SCEN * ntot),
        replay_share_over=sum(m['over'] > 0 for m in pert) / len(pert), replay_max_tard_s=max(m['max_tard'] for m in pert))


if __name__ == '__main__':
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    name = sys.argv[1]
    study = STUDY_ROOT / name
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    shift_end = 600 * 60 if name == 'second_case' else 16 * 3600
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    with ProcessPoolExecutor(workers) as pool:
        res = dict(pool.map(replay, [(study, sp, shift_end) for sp in specs]))
    out = STUDY_ROOT / 'results' / ('%s_replay.json' % name)
    out.write_text(json.dumps(res, indent=1) + '\n', encoding='utf8')
    ok = [v for v in res.values() if v]
    print(json.dumps(dict(series=len(res), with_K=len(ok), fail_shift_hard=sum(not v['meets_shift_hard'] for v in ok))))
