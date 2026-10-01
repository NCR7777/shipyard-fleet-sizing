"""Bound L4: column-generation lower bound on late blocks for the shared four-transporter
single-carry problem under a delay cap (no coupling: every block is served by one transporter).

Master (LP relaxation of set partitioning): min sum_r c_r lam_r + M sum_i art_i
  s.t. sum_r a_ir lam_r + art_i = 1 (every block), sum_{r in R_k} lam_r <= 1 (every transporter k),
  lam, art >= 0.
A route r of transporter k is a block sequence from k's start position with earliest starts
s_{j+1} = max(r_{j+1}, s_j + D_j + tE[j][j+1]) that respects the hard windows s <= d + T - D;
c_r counts its late visits (s > d - D) and a_ir counts its visits to block i. Routes come from
ng-route labelling (memory = 8 nearest blocks), a superset of elementary routes; artificial
columns only add freedom. Both keep the LP a relaxation, so its value and the Lagrangian value
z + sum_k min(0, rc_k*) (exact pricing) are lower bounds on the late blocks of any schedule.
Late blocks >= ceil(bound - 1e-6).

  python bounds_colgen.py <seed> [T_min] [time_limit_s] [ng]
  python bounds_colgen.py selfcheck          # brute force on tiny random instances
"""
import heapq
import itertools
import json
import math
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'earlier_study' / 'code'))
for sub in ('common', 'search', 'instances'):
    sys.path.insert(0, str(ROOT / 'paper' / 'code' / sub))
from ortools.linear_solver import pywraplp      # noqa: E402

OUT = ROOT / 'fleet_sizing' / 'results' / 'bounds_L4'
BIG = 30.0
clock = time.process_time        # budgets are single-thread CPU seconds (4 h per instance)


class Inst:
    def __init__(self, D, r, due, tE, tE0, cap_s):
        self.n, self.K = len(D), len(tE0)
        self.D, self.r, self.tE, self.tE0 = D, r, tE, tE0
        self.on = [due[i] - D[i] for i in range(self.n)]              # latest on-time start
        self.L = [due[i] + cap_s - D[i] for i in range(self.n)]       # latest start under the cap
        self.succ = [[j for j in range(self.n) if j != i and r[i] + D[i] + tE[i][j] <= self.L[j]]
                     for i in range(self.n)]


def from_instance(d, cap_s):
    T = d['tasks']
    return Inst([t['load'] + t['tauL'] + t['unload'] for t in T], [t['release'] for t in T],
                [t['due'] for t in T], d['tauE'], d['tauE_start'], cap_s)


def route_cost(I, k, seq):
    t, last, c = 0, None, 0
    for i in seq:
        t = max(I.r[i], I.tE0[k][i] if last is None else t + I.D[last] + I.tE[last][i])
        if t > I.L[i]:
            return None
        c += t > I.on[i]
        last = i
    return c


def price(I, k, pi, mu, ng_sets, max_cols=40, deadline=None, cap=None):
    """ng-route labelling; exact when cap is None, otherwise at most `cap` labels per task (heuristic).
    Returns (completed and exact, min reduced cost, columns with rc < 0)."""
    labels = [[] for _ in range(I.n)]
    heap, cnt = [], 0
    for i in range(I.n):
        t = max(I.r[i], I.tE0[k][i])
        if t <= I.L[i]:
            lab = (t, (t > I.on[i]) - pi[i], 1 << i, (i,))
            labels[i].append(lab)
            heapq.heappush(heap, (t, cnt, i, lab))
            cnt += 1
    found = []
    while heap:
        if deadline and clock() > deadline:
            return False, None, []
        t, _, i, lab = heapq.heappop(heap)
        if lab not in labels[i]:
            continue
        _, c, mem, seq = lab
        if c - mu < -1e-9:
            found.append((c - mu, seq))
        tDi = t + I.D[i]
        for j in I.succ[i]:
            if mem >> j & 1:
                continue
            t2 = max(I.r[j], tDi + I.tE[i][j])
            if t2 > I.L[j]:
                continue
            c2 = c + (t2 > I.on[j]) - pi[j]
            mem2 = (mem & ng_sets[j]) | (1 << j)
            L = labels[j]
            if any(ta <= t2 and ca <= c2 + 1e-12 and (ma & mem2) == ma for ta, ca, ma, _ in L):
                continue
            new = (t2, c2, mem2, seq + (j,))
            labels[j] = [x for x in L if not (t2 <= x[0] and c2 <= x[1] + 1e-12 and (mem2 & x[2]) == mem2)] + [new]
            if cap and len(labels[j]) > cap:
                labels[j].sort(key=lambda x: x[1])
                labels[j] = labels[j][:cap]
                if new not in labels[j]:
                    continue
            heapq.heappush(heap, (t2, cnt, j, new))
            cnt += 1
    found.sort()
    cols, seen = [], set()
    for rc, seq in found:
        if seq not in seen:
            seen.add(seq)
            cols.append(seq)
        if len(cols) >= max_cols:
            break
    return cap is None, (found[0][0] if found else 0.0), cols


def colgen(I, init_routes, time_limit, ng=8, verbose=True, smooth=0.7, heur_cap=12, exact_every=10):
    near = [sorted(range(I.n), key=lambda j: I.tE[j][i] if j != i else -1)[:ng + 1] for i in range(I.n)]
    ng_sets = [sum(1 << j for j in near[i]) for i in range(I.n)]
    lp = pywraplp.Solver.CreateSolver('GLOP')
    art = [lp.NumVar(0, lp.infinity(), 'a%d' % i) for i in range(I.n)]
    cov = [lp.Constraint(1, 1) for _ in range(I.n)]
    veh = [lp.Constraint(-lp.infinity(), 1) for _ in range(I.K)]
    obj = lp.Objective()
    for i in range(I.n):
        cov[i].SetCoefficient(art[i], 1)
        obj.SetCoefficient(art[i], BIG)
    obj.SetMinimization()
    known = set()

    def add(k, seq, c):
        if (k, seq) in known:
            return False
        known.add((k, seq))
        v = lp.NumVar(0, lp.infinity(), '')
        for i in set(seq):
            cov[i].SetCoefficient(v, seq.count(i))
        veh[k].SetCoefficient(v, 1)
        obj.SetCoefficient(v, c)
        return True

    for k, seq in init_routes:
        if seq:
            c = route_cost(I, k, tuple(seq))
            assert c is not None
            add(k, tuple(seq), c)
    t0, c0 = time.time(), clock()
    deadline = c0 + time_limit
    lb, it, log, converged, center = -math.inf, 0, [], False, None
    while True:
        it += 1
        st = lp.Solve()
        if st != pywraplp.Solver.OPTIMAL:       # GLOP occasionally fails on the warm start: re-solve cold
            P = pywraplp.MPSolverParameters
            for alg in (None, P.PRIMAL, P.DUAL):
                prm = P()
                prm.SetIntegerParam(P.INCREMENTALITY, P.INCREMENTALITY_OFF)
                if alg is not None:
                    prm.SetIntegerParam(P.LP_ALGORITHM, alg)
                st0, st = st, lp.Solve(prm)
                log.append(dict(it=it, resolve=('cold' if alg is None else 'cold_%d' % alg), status_before=st0, status=st))
                if st == pywraplp.Solver.OPTIMAL:
                    break
        if st != pywraplp.Solver.OPTIMAL:       # still failing: move the same model to another simplex code
            from ortools.linear_solver import linear_solver_pb2
            proto = linear_solver_pb2.MPModelProto()
            lp.ExportModelToProto(proto)
            for backend in ('CLP', 'HIGHS_LP'):
                new = pywraplp.Solver.CreateSolver(backend)
                if new is None or new.LoadModelFromProto(proto):
                    continue
                st = new.Solve()
                log.append(dict(it=it, switch_backend=backend, status=st))
                if st == pywraplp.Solver.OPTIMAL:
                    cs = new.constraints()
                    assert len(cs) == I.n + I.K
                    lp, cov, veh, obj = new, cs[:I.n], cs[I.n:], new.Objective()   # add() sees the new model
                    break
        assert st == pywraplp.Solver.OPTIMAL, st
        z = obj.Value()
        pi_r = [x.dual_value() for x in cov]
        mu_r = [x.dual_value() for x in veh]
        alpha = smooth if center is not None else 0.0
        # heuristic pass on the master duals first; exact pass (bound) when it fails or periodically
        if heur_cap and it % exact_every:
            hc = []
            for k in range(I.K):
                _, _, cs = price(I, k, pi_r, 0.0, ng_sets, deadline=deadline, cap=heur_cap)
                for seq in cs:
                    c = route_cost(I, k, seq)
                    if c is not None:
                        rc_r = c - sum(pi_r[i] for i in seq) - mu_r[k]
                        if rc_r < -1e-9:
                            hc.append((rc_r, k, seq, c))
            if hc:
                added = sum(add(k, seq, c) for _, k, seq, c in sorted(hc)[:40 * I.K])
                log.append(dict(it=it, z=round(z, 4), lb=round(lb, 4), heur=True, added=added, cols=len(known),
                                wall=round(time.time() - t0, 1)))
                if verbose and it % 10 == 0:
                    print(json.dumps(log[-1]), flush=True)
                if added and clock() < deadline:
                    continue
        while True:
            pi = [alpha * a_ + (1 - alpha) * b_ for a_, b_ in zip(center, pi_r)] if alpha else pi_r
            best_k, cand, complete = [], [], True
            for k in range(I.K):
                ok, rc, cs = price(I, k, pi, 0.0, ng_sets, deadline=deadline)
                complete &= ok
                best_k.append(rc)
                for seq in cs:
                    c = route_cost(I, k, seq)
                    if c is not None:
                        rc_r = c - sum(pi_r[i] for i in seq) - mu_r[k]
                        cand.append((rc_r, k, seq, c))
            if not complete:
                break
            L = sum(pi) + sum(min(0.0, x) for x in best_k)
            if L > lb:
                lb, center = L, pi
            neg = [x for x in cand if x[0] < -1e-9]
            if neg or alpha == 0.0:
                break
            alpha = 0.0                     # mis-pricing: price at the master duals
        if not complete:
            break
        added = sum(add(k, seq, c) for _, k, seq, c in sorted(neg)[:40 * I.K])
        if alpha == 0.0 and not neg:
            converged, lb = True, max(lb, z)
        log.append(dict(it=it, z=round(z, 4), lb=round(lb, 4), alpha=alpha, added=added,
                        cols=len(known), wall=round(time.time() - t0, 1)))
        if verbose and (it % 10 == 0 or converged):
            print(json.dumps(log[-1]), flush=True)
        if converged or not added or clock() > deadline or z - lb < 1e-6:
            break
    return dict(lp_bound=lb, late_lb=max(0, math.ceil(lb - 1e-6)) if lb > -math.inf else 0, converged=converged,
                iterations=it, columns=len(known), wall_s=time.time() - t0, cpu_s=clock() - c0, log=log, rmp=z,
                cols=sorted(known))


def integer_master(I, cols, time_limit=1800):
    """Set partitioning over the elementary generated routes (<= 1 route per transporter). Any solution is
    a feasible single-carry schedule, so its late count is an upper bound. Returns (late, routes) or None."""
    el = [(k, seq, route_cost(I, k, seq)) for k, seq in cols if len(set(seq)) == len(seq)]
    el = [x for x in el if x[2] is not None]
    m = pywraplp.Solver.CreateSolver('SCIP')
    m.SetTimeLimit(int(1000 * time_limit))
    x = [m.BoolVar('') for _ in el]
    for i in range(I.n):
        m.Add(sum(x[q] for q, (k, seq, c) in enumerate(el) if i in seq) == 1)
    for k in range(I.K):
        m.Add(sum(x[q] for q, e in enumerate(el) if e[0] == k) <= 1)
    m.Minimize(sum(c * x[q] for q, (k, seq, c) in enumerate(el)))
    st = m.Solve()
    if st not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return None
    routes = {el[q][0]: el[q][1] for q in range(len(el)) if x[q].solution_value() > 0.5}
    return round(m.Objective().Value()), routes, st == pywraplp.Solver.OPTIMAL, m.Objective().BestBound()


def brute(I):
    """Exact minimum late count by enumerating assignments and orders (tiny instances only)."""
    best = math.inf
    for assign in itertools.product(range(I.K), repeat=I.n):
        tot = 0
        for k in range(I.K):
            tasks = [i for i in range(I.n) if assign[i] == k]
            bk = math.inf
            for perm in itertools.permutations(tasks):
                c = route_cost(I, k, perm)
                if c is not None:
                    bk = min(bk, c)
            tot += bk
            if tot >= best:
                break
        best = min(best, tot)
    return best


def selfcheck(trials=40):
    rng = random.Random(7)
    checked = 0
    for _ in range(trials):
        n, K = rng.randint(4, 6), 2
        D = [rng.randint(5, 20) for _ in range(n)]
        r = [rng.choice([0, 0, 20, 40]) for _ in range(n)]
        due = [r[i] + D[i] + rng.randint(0, 40) for i in range(n)]
        tE = [[0 if i == j else rng.randint(1, 15) for j in range(n)] for i in range(n)]
        tE0 = [[rng.randint(0, 10) for _ in range(n)] for _ in range(K)]
        I = Inst(D, r, due, tE, tE0, 30)
        opt = brute(I)
        if opt == math.inf:
            continue
        # initial columns: one block per route is always capped-feasible only if windows allow; use a
        # greedy feasible schedule from the brute force instead: single routes of each block
        init = [(k, (i,)) for i in range(n) for k in range(K) if route_cost(I, k, (i,)) is not None]
        res = colgen(I, init, 60, ng=3, verbose=False)
        assert res['converged'], res
        assert res['lp_bound'] <= opt + 1e-6, (res['lp_bound'], opt)
        ip = integer_master(I, res['cols'], 60)
        if ip:
            assert ip[0] >= opt and ip[0] == sum(route_cost(I, k, seq) for k, seq in ip[1].items()), (ip, opt)
            assert sorted(i for seq in ip[1].values() for i in seq) == list(range(n))
        checked += 1
    print('colgen self-check passed on %d random instances (bound <= brute-force optimum)' % checked)


def main(seed, cap_min=120, time_limit=14400, ng=8):
    import instance_setup as E
    import pool_all
    cap_s = 60 * cap_min
    d = E.make('425', 4, 'liu', 'short', 'baseline', seed)
    I = from_instance(d, cap_s)
    pool_all._init()
    best = pool_all.work(('liu_short_baseline', '425', 4, None, 'flex', True, cap_s))
    if seed in best['best_at_kmax']:
        order, team = best['best_at_kmax'][seed]['schedule']
        team = {int(i): v for i, v in team.items()}
        init = [(k, tuple(i for i in order if team[i][0] == k)) for k in range(4)]
        ub = sum(route_cost(I, k, seq) for k, seq in init)
    else:                   # seeds 111-130 have no earlier runs; the bound does not depend on the start columns
        init, ub = [], None
    res = colgen(I, init, time_limit, ng)
    ip = integer_master(I, res.pop('cols'))
    if ip:
        # replay the integer solution in the scheduling evaluator (single carry, the transporter's own order)
        from core import Inst as CInst, evaluate
        CI = CInst(d)
        order = sorted((i for seq in ip[1].values() for i in seq), key=lambda i: next(
            (seq.index(i), k) for k, seq in ip[1].items() if i in seq))
        tm = {i: (k,) for k, seq in ip[1].items() for i in seq}
        ev = evaluate(CI, order, tm, 0, detail=True)
        late = [ev['comp'][i] - CI.due[i] for i in range(CI.n)]
        res.update(ip_late=ip[0], ip_optimal=ip[2], ip_bound=ip[3], ip_routes={k: list(v) for k, v in ip[1].items()},
                   ip_replay_late=sum(x > 0 for x in late), ip_replay_max_tard_s=max(0, max(late)))
    out = dict(seed=seed, T_min=cap_min, ng=ng, ub_late_known=ub, **{k: v for k, v in res.items() if k != 'log'})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ('seed%d_T%d.json' % (seed, cap_min))).write_text(json.dumps(dict(out, log=res['log'])) + '\n', encoding='utf8')
    print(json.dumps(out), flush=True)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'selfcheck':
        selfcheck()
    else:
        main(int(a[0]), int(a[1]) if len(a) > 1 else 120, float(a[2]) if len(a) > 2 else 14400, int(a[3]) if len(a) > 3 else 8)
