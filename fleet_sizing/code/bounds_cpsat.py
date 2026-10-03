"""Bound L3: full CP-SAT model of the shared four-transporter single-carry problem under a
delay cap. Every block is served (no skipping); start s_i in [r_i, d_i + T - D_i]; one circuit
per transporter (distinct start positions); precedence s_j >= s_i + D_i + tE[i][j] on used arcs
(arcs pruned when the earliest completion of i plus travel exceeds the latest start of j);
o_i = 1 iff s_i <= d_i - D_i; maximise sum o_i. Hint: best known capped schedule (pooled).
Reports the proven upper bound on on-time blocks, i.e. a lower bound on late blocks.

  python bounds_cpsat.py <seed> <seconds> <workers> [T_min]
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for sub in ('common', 'search', 'instances'):
    sys.path.insert(0, str(ROOT / 'paper' / 'code' / sub))
from ortools.sat.python import cp_model          # noqa: E402

OUT = ROOT / 'fleet_sizing' / 'results' / 'bounds_L3'


def build(d, cap_s):
    T, V = d['tasks'], d['vehicles']
    n, K = len(T), len(V)
    D = [t['load'] + t['tauL'] + t['unload'] for t in T]
    rel = [t['release'] for t in T]
    due = [t['due'] for t in T]
    tE, tE0 = d['tauE'], d['tauE_start']
    ls = [due[i] + cap_s - D[i] for i in range(n)]
    m = cp_model.CpModel()
    s = [m.NewIntVar(rel[i], ls[i], 's%d' % i) for i in range(n)]
    o = [m.NewBoolVar('o%d' % i) for i in range(n)]
    for i in range(n):
        m.Add(s[i] <= due[i] - D[i]).OnlyEnforceIf(o[i])
        m.Add(s[i] >= due[i] - D[i] + 1).OnlyEnforceIf(o[i].Not())
    y = {(i, k): m.NewBoolVar('y%d_%d' % (i, k)) for i in range(n) for k in range(K)}
    for i in range(n):
        m.AddExactlyOne(y[i, k] for k in range(K))
    x0, x = {}, {}
    for k in range(K):
        arcs = [(0, 0, m.NewBoolVar('u%d' % k))]
        for i in range(n):
            arcs.append((i + 1, i + 1, y[i, k].Not()))
            arcs.append((i + 1, 0, m.NewBoolVar('e%d_%d' % (k, i))))
            if tE0[k][i] <= ls[i]:
                b = m.NewBoolVar('x0_%d_%d' % (k, i))
                x0[k, i] = b
                arcs.append((0, i + 1, b))
                m.Add(s[i] >= tE0[k][i]).OnlyEnforceIf(b)
        for i in range(n):
            for j in range(n):
                if i != j and rel[i] + D[i] + tE[i][j] <= ls[j]:
                    b = m.NewBoolVar('x%d_%d_%d' % (k, i, j))
                    x[k, i, j] = b
                    arcs.append((i + 1, j + 1, b))
                    m.Add(s[j] >= s[i] + D[i] + tE[i][j]).OnlyEnforceIf(b)
        m.AddCircuit(arcs)
    m.Maximize(sum(o))
    return m, s, o, y, x0, x


def main(seed, seconds, workers, cap_min=120):
    import instance_setup as E
    import pool_all
    cap_s = 60 * cap_min
    d = E.make('425', 4, 'liu', 'short', 'baseline', seed)
    m, s, o, y, x0, x = build(d, cap_s)
    pool_all._init()
    best = pool_all.work(('liu_short_baseline', '425', 4, None, 'flex', True, cap_s))
    hint_on = None
    sched = best.get('best_at_kmax', {}).get(seed, {}).get('schedule')
    if sched:
        order, team = sched
        team = {int(i): v for i, v in team.items()}
        K = 4
        seqs = [[] for _ in range(K)]
        for i in order:
            seqs[team[i][0]].append(i)
        # earliest-start replay for the hint
        T = d['tasks']
        Dd = [t['load'] + t['tauL'] + t['unload'] for t in T]
        avail, last, start = [0] * K, [-1] * K, {}
        for i in order:
            k = team[i][0]
            st = max(T[i]['release'], avail[k] + (d['tauE_start'][k][i] if last[k] < 0 else d['tauE'][last[k]][i]))
            start[i] = st
            avail[k], last[k] = st + Dd[i], i
        for i in range(len(T)):
            m.AddHint(s[i], start[i])
            m.AddHint(o[i], int(start[i] <= T[i]['due'] - Dd[i]))
            for k in range(K):
                m.AddHint(y[i, k], int(team[i][0] == k))
        nxt = {(k, a): b for k, q in enumerate(seqs) for a, b in zip(q, q[1:])}
        first = {k: q[0] for k, q in enumerate(seqs) if q}
        for (k, i), v in x0.items():
            m.AddHint(v, int(first.get(k) == i))
        for (k, i, j), v in x.items():
            m.AddHint(v, int(nxt.get((k, i)) == j))
        hint_on = sum(start[i] <= T[i]['due'] - Dd[i] for i in range(len(T)))
    sol = cp_model.CpSolver()
    sol.parameters.max_time_in_seconds = seconds
    sol.parameters.num_workers = workers
    sol.parameters.random_seed = seed
    t0 = time.time()
    st = sol.Solve(m)
    out = dict(seed=seed, T_min=cap_min, seconds=seconds, workers=workers, status=sol.StatusName(st),
               hint_on_time=hint_on, wall_s=time.time() - t0)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        out.update(found_on_time=int(round(sol.ObjectiveValue())), ub_on_time=int(sol.BestObjectiveBound() + 1e-6))
        out['late_lb'] = 97 - out['ub_on_time']
    elif st == cp_model.INFEASIBLE:
        out.update(ub_on_time=-1, late_lb=None, note='infeasible under the cap')
    else:
        out.update(ub_on_time=int(sol.BestObjectiveBound() + 1e-6) if sol.BestObjectiveBound() < 1e9 else 97)
        out['late_lb'] = 97 - out['ub_on_time']
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ('seed%d_T%d.json' % (seed, cap_min))).write_text(json.dumps(out) + '\n', encoding='utf8')
    print(json.dumps(out), flush=True)


if __name__ == '__main__':
    a = sys.argv[1:]
    main(int(a[0]), float(a[1]), int(a[2]), int(a[3]) if len(a) > 3 else 120)
