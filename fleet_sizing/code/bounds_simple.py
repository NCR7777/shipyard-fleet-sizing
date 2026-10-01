"""Lower bounds on late blocks for the shared four-transporter single-carry problem
(short handling, baseline due dates, seeds 101-110) under a delay cap T (default 120 min).

L1 capped energy bound. For a window [t1, t2]: every block with r_i >= t1 and d_i + T <= t2 is
served inside the window whether or not it is late (mandatory, M); a block with r_i >= t1 and
d_i <= t2 < d_i + T is inside only if on time (optional, O). With a_i the smallest member work
|S|(D_i + delta[|S|>1] + e_i) and e_hat the largest e_i in the window, the work of M and of the
on-time part of O must fit into K(t2 - t1 + e_hat) (the first approach of each transporter may
precede t1). If M alone does not fit the instance is infeasible under the cap; otherwise the
fewest blocks of O to drop (largest a_i first) bounds the late blocks. t1 ranges over releases,
t2 over due times and due times + T.

L2 cumulative relaxation (CP-SAT): each block i an interval [s_i - e_i, s_i + D_i) with start
s_i in [r_i, d_i + T - D_i], capacity K; o_i = 1 iff s_i <= d_i - D_i; maximise sum o_i.
Removing routes (except the shortest approach e_i) makes this a valid relaxation.

  python bounds_simple.py [T_min] [L2_seconds]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for sub in ('common', 'search', 'instances'):
    sys.path.insert(0, str(ROOT / 'paper' / 'code' / sub))
import instance_setup as E                               # noqa: E402
from core import minimal_teams                     # noqa: E402

OUT = ROOT / 'fleet_sizing' / 'results'
SEEDS = range(101, 111)


def prep(d, caps):
    T = d['tasks']
    n = len(T)
    D = [t['load'] + t['tauL'] + t['unload'] for t in T]
    dl = d['meta']['delta_s']
    tE, tE0 = d['tauE'], d['tauE_start']
    e = [min([tE0[k][i] for k in range(len(caps))] + [tE[j][i] for j in range(n) if j != i]) for i in range(n)]
    a = [min(len(S) * (D[i] + (dl if len(S) > 1 else 0) + e[i]) for S in minimal_teams(caps, T[i]['mass'], 'flex', d['meta']['max_team']))
         for i in range(n)]
    return T, D, e, a


def energy_capped(d, caps, cap_s):
    T, D, e, a = prep(d, caps)
    K = len(caps)
    rel = [t['release'] for t in T]
    due = [t['due'] for t in T]
    best = 0
    for t1 in sorted(set(rel)):
        for t2 in sorted(set(due) | {x + cap_s for x in due}):
            if t2 <= t1:
                continue
            M = [i for i in range(len(T)) if rel[i] >= t1 and due[i] + cap_s <= t2]
            O = [i for i in range(len(T)) if rel[i] >= t1 and due[i] <= t2 < due[i] + cap_s]
            if not M and not O:
                continue
            capy = K * (t2 - t1 + max(e[i] for i in M + O))
            base = sum(a[i] for i in M)
            if base > capy:
                return None                             # infeasible under the cap
            load = sorted((a[i] for i in O), reverse=True)
            tot, drop = base + sum(load), 0
            while tot > capy:
                tot -= load[drop]
                drop += 1
            best = max(best, drop)
    return best


def cumulative(d, caps, cap_s, seconds):
    from ortools.sat.python import cp_model
    T, D, e, a = prep(d, caps)
    m = cp_model.CpModel()
    o, iv = [], []
    for i, t in enumerate(T):
        s = m.NewIntVar(t['release'], t['due'] + cap_s - D[i], 's%d' % i)
        oi = m.NewBoolVar('o%d' % i)
        m.Add(s <= t['due'] - D[i]).OnlyEnforceIf(oi)
        b = m.NewIntVar(t['release'] - e[i], t['due'] + cap_s - D[i] - e[i], 'b%d' % i)
        m.Add(b == s - e[i])
        iv.append(m.NewFixedSizeIntervalVar(b, D[i] + e[i], 'i%d' % i))
        o.append(oi)
    m.AddCumulative(iv, [1] * len(T), len(caps))
    m.Maximize(sum(o))
    sol = cp_model.CpSolver()
    sol.parameters.max_time_in_seconds = seconds
    sol.parameters.num_workers = 8
    st = sol.Solve(m)
    if st == cp_model.INFEASIBLE:
        return dict(status='INFEASIBLE', ub_on_time=-1)
    return dict(status=sol.StatusName(st), ub_on_time=int(sol.BestObjectiveBound() + 1e-6), found=int(sol.ObjectiveValue()))


def main(cap_min, l2_seconds):
    cap_s = 60 * cap_min
    caps = [425] * 4
    rows = []
    for s in SEEDS:
        d = E.make('425', 4, 'liu', 'short', 'baseline', s)
        b1 = energy_capped(d, caps, cap_s)
        c = cumulative(d, caps, cap_s, l2_seconds)
        b2 = 97 - c['ub_on_time'] if c['ub_on_time'] >= 0 else None
        rows.append(dict(seed=s, L1_late_lb=b1, L2=c, L2_late_lb=b2))
        print(json.dumps(rows[-1]), flush=True)
    tot = lambda k: None if any(r[k] is None for r in rows) else sum(r[k] for r in rows)
    out = dict(T_min=cap_min, rows=rows, sum_L1=tot('L1_late_lb'), sum_L2=tot('L2_late_lb'), needed=49)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ('bounds_L12_T%d.json' % cap_min)).write_text(json.dumps(out, indent=1) + '\n', encoding='utf8')
    print(json.dumps({k: out[k] for k in ('sum_L1', 'sum_L2', 'needed')}))


if __name__ == '__main__':
    a = sys.argv[1:]
    main(int(a[0]) if a else 120, float(a[1]) if len(a) > 1 else 600)
