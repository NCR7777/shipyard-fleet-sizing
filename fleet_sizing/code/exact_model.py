"""Exact arm of the exact comparison on single-batch instances.

Fewest late blocks of one fixed fleet on one slice under a hard delay cap T. Every block is served by exactly one minimal
feasible team (core.minimal_teams, flex, kappa = 3); start s_i in [r_i, d_i + T - D_i - delta*coop_i];
o_i = 1 only if the block completes by d_i; maximise sum o_i. One circuit per transporter (first K
start positions), precedence on used arcs, arcs pruned by the capped latest start, redundant
cumulative constraint (each team member is busy for e_i + D_i + delta*coop_i; e_i = shortest approach),
and sum o_i <= the route-relaxation bound (route_bound).
CP-SAT: one worker with interleave_search (the strategy portfolio run in turn on one thread), random_seed 0;
budget max_deterministic_time only; no hints. Eight workers with interleave_search did not give reproducible search
paths (determinism check), so a single thread with deterministic time is used. The recorded bound is the larger of CP-SAT's bound and the route bound.
Every solution is replayed with core.evaluate (global order by start time, ties by index, earliest
start): late count <= CP-SAT value, maximum delay <= T, legal teams.

  python exact_model.py selfcheck          # checks 1-4 and the determinism test
"""
import json
import math
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
ROOT = STUDY_ROOT.parent
for p in (str(STUDY_ROOT / 'solver' / 'common'), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
from ortools.sat.python import cp_model                    # noqa: E402
from core import Inst, evaluate, minimal_teams              # noqa: E402
from fleet_scan import caps_of                                   # noqa: E402  (MX heavy members 550 t; SUB is pricing only)
from exact_slices import k_lb, triangle_ok                     # noqa: E402,F401

CAP_S = 7200
WORKERS = 1


def _cpu():
    import os
    t = os.times()
    return t.user + t.system


def fleet(d, caps, cap_s=CAP_S):
    e = dict(d, vehicles=[dict(d['vehicles'][k], cap=c) for k, c in enumerate(caps)], tauE_start=d['tauE_start'][:len(caps)])
    e['meta'] = dict(d['meta'], objective_mode='cap', tmax_s=cap_s, crew_team=None)
    return e


class Capped:
    def __init__(self, d, cap_s=CAP_S, cumulative=True, route=True, build=True):
        T, V = d['tasks'], d['vehicles']
        n, K = len(T), len(V)
        meta = d['meta']
        if (meta.get('delta_turn_s') or 0) != 0:
            raise ValueError('turn-dependent coupling time not supported')
        cap = [v['cap'] for v in V]
        rel = [t['release'] for t in T]
        due = [t['due'] for t in T]
        D = [t['load'] + t['tauL'] + t['unload'] for t in T]
        dl = meta['delta_s']
        tE, tE0 = d['tauE'], d['tauE_start']
        self.n, self.K, self.cap_s = n, K, cap_s
        teams = [minimal_teams(cap, T[i]['mass'], 'flex', meta['max_team']) for i in range(n)]
        self.structural = all(teams)
        # a team is usable only if its own service fits within the cap
        teams = [[S for S in teams[i] if rel[i] + D[i] + (dl if len(S) > 1 else 0) <= due[i] + cap_s] for i in range(n)]
        self.teams = teams
        self.trivial = not self.structural or any(not ts for ts in teams)
        self.route_ub = None
        if self.trivial or not build:
            return
        m = cp_model.CpModel()
        o = [m.NewBoolVar('o%d' % i) for i in range(n)]
        z, coop = {}, []
        for i in range(n):
            for S in teams[i]:
                z[i, S] = m.NewBoolVar('z%d_%s' % (i, '_'.join(map(str, S))))
            m.AddExactlyOne(z[i, S] for S in teams[i])
            cz = [z[i, S] for S in teams[i] if len(S) > 1]
            coop.append(sum(cz) if cz else 0)
        can = [[any(k in S for S in teams[i]) for k in range(K)] for i in range(n)]
        y = {}
        for i in range(n):
            for k in range(K):
                if can[i][k]:
                    y[i, k] = m.NewBoolVar('y%d_%d' % (i, k))
                    m.Add(y[i, k] == sum(z[i, S] for S in teams[i] if k in S))
        ls = [due[i] + cap_s - D[i] for i in range(n)]          # latest start under the cap (single carry)
        s = []
        for i in range(n):
            si = m.NewIntVar(rel[i], ls[i], 's%d' % i)
            m.Add(si + D[i] + dl * coop[i] <= due[i] + cap_s)
            m.Add(si + D[i] + dl * coop[i] <= due[i]).OnlyEnforceIf(o[i])
            s.append(si)
        ec = [rel[i] + D[i] + (0 if any(len(S) == 1 for S in teams[i]) else dl) for i in range(n)]
        for k in range(K):
            tk = [i for i in range(n) if can[i][k]]
            node = {i: q + 1 for q, i in enumerate(tk)}
            unused = m.NewBoolVar('u%d' % k)
            arcs = [(0, 0, unused)]
            for i in tk:
                arcs.append((node[i], node[i], y[i, k].Not()))
                m.AddImplication(y[i, k], unused.Not())
                arcs.append((node[i], 0, m.NewBoolVar('e%d_%d' % (k, i))))
                if tE0[k][i] <= ls[i]:
                    b = m.NewBoolVar('x0_%d_%d' % (k, i))
                    arcs.append((0, node[i], b))
                    if tE0[k][i] > rel[i]:
                        m.Add(s[i] >= tE0[k][i]).OnlyEnforceIf(b)
            for i in tk:
                for j in tk:
                    if i == j or ec[i] + tE[i][j] > ls[j]:
                        continue
                    b = m.NewBoolVar('x%d_%d_%d' % (k, i, j))
                    arcs.append((node[i], node[j], b))
                    m.Add(s[j] >= s[i] + D[i] + dl * coop[i] + tE[i][j]).OnlyEnforceIf(b)
            m.AddCircuit(arcs)
        if cumulative:
            e = [min([tE0[k][i] for k in range(K)] + [tE[j][i] for j in range(n) if j != i]) for i in range(n)]
            iv, dem = [], []
            for i in range(n):
                for S in teams[i]:
                    size = e[i] + D[i] + (dl if len(S) > 1 else 0)
                    st_ = m.NewIntVar(rel[i] - e[i], ls[i] - e[i], 'b%d_%d' % (i, len(iv)))
                    m.Add(st_ == s[i] - e[i]).OnlyEnforceIf(z[i, S])
                    iv.append(m.NewOptionalFixedSizeIntervalVar(st_, size, z[i, S], 'iv%d' % len(iv)))
                    dem.append(len(S))
            m.AddCumulative(iv, dem, K)
        if route and triangle_ok(d):             # the bound is valid only under the triangle inequality
            self.route_ub = route_bound(d)
            m.Add(sum(o) <= self.route_ub)
        m.Maximize(sum(o))
        self.m, self.o, self.z, self.s = m, o, z, s

    def solve(self, det_time, workers=WORKERS, seed=0):
        if self.trivial:
            return dict(status='INFEASIBLE', reason='structural' if not self.structural else 'window', late=None,
                        late_lb=None, det_time=0.0, wall_s=0.0, cpu_s=0.0, n=self.n, K=self.K, det_budget=det_time, route_lb=None,
                        proven=True)
        sol = cp_model.CpSolver()
        sol.parameters.max_deterministic_time = float(det_time)
        sol.parameters.num_workers = int(workers)
        sol.parameters.interleave_search = True
        sol.parameters.random_seed = int(seed)
        t0, c0 = time.time(), _cpu()
        st = sol.Solve(self.m)
        out = dict(status=sol.StatusName(st), n=self.n, K=self.K, det_time=sol.deterministic_time, wall_s=time.time() - t0,
                   cpu_s=_cpu() - c0,
                   det_budget=det_time, route_lb=None if self.route_ub is None else self.n - self.route_ub)
        rl = 0 if self.route_ub is None else self.n - self.route_ub
        bound = lambda: max(rl, min(self.n, max(0, self.n - int(math.floor(sol.BestObjectiveBound() + 1e-6)))))
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            out.update(late=self.n - int(round(sol.ObjectiveValue())), late_lb=bound(),
                       start={i: sol.Value(self.s[i]) for i in range(self.n)},
                       team={i: list(S) for (i, S), v in self.z.items() if sol.Value(v)})
        elif st == cp_model.INFEASIBLE:
            out.update(late=None, late_lb=None)
        else:
            out.update(late=None, late_lb=bound())
        out['proven'] = st in (cp_model.OPTIMAL, cp_model.INFEASIBLE) or (out['late'] is not None and out['late'] == out['late_lb'])
        return out


def route_bound(d, det_time=60.0):
    """Upper bound on the on-time count by a route relaxation (synchronisation, the cap and the serving of late
    blocks dropped). Each transporter k takes the blocks it can join (alone if Q_k >= m_i, else as a member of a
    minimal team, occupying D_i + delta); a DP over (set, last) with earliest completion gives every set k can
    serve all on time (release, own start position, empty travel). Master: one maximal set per transporter;
    block i counts if the transporters holding it contain a minimal team. Valid for the capped late count under
    the triangle inequality (removing late blocks delays no on-time block; exact_ontime docstring)."""
    T, V = d['tasks'], d['vehicles']
    n, K = len(T), len(V)
    dl, cap = d['meta']['delta_s'], [v['cap'] for v in V]
    rel = [t['release'] for t in T]
    due = [t['due'] for t in T]
    D = [t['load'] + t['tauL'] + t['unload'] for t in T]
    tE, tE0 = d['tauE'], d['tauE_start']
    teams = [[S for S in minimal_teams(cap, T[i]['mass'], 'flex', d['meta']['max_team'])
              if rel[i] + D[i] + (dl if len(S) > 1 else 0) <= due[i]] for i in range(n)]
    m = cp_model.CpModel()
    cover = [[[] for _ in range(K)] for _ in range(n)]
    for k in range(K):
        can = [i for i in range(n) if any(k in S for S in teams[i])]
        dur = {i: D[i] + (0 if cap[k] >= T[i]['mass'] else dl) for i in can}
        best = {}
        for i in can:
            c = max(rel[i], tE0[k][i]) + dur[i]
            if c <= due[i]:
                best[1 << i, i] = c
        frontier = dict(best)
        while frontier:
            nxt = {}
            for (mask, a), c0 in frontier.items():
                for j in can:
                    if mask >> j & 1:
                        continue
                    c = max(rel[j], c0 + tE[a][j]) + dur[j]
                    key = (mask | 1 << j, j)
                    if c <= due[j] and c < best.get(key, math.inf):
                        best[key] = nxt[key] = c
            frontier = nxt
        sets = {mask for mask, _ in best}
        maximal = [s for s in sets if not any((s | 1 << j) in sets for j in can if not s >> j & 1)] or [0]
        xs = [m.NewBoolVar('r%d_%d' % (k, q)) for q in range(len(maximal))]
        m.AddExactlyOne(xs)
        for s, x in zip(maximal, xs):
            for i in can:
                if s >> i & 1:
                    cover[i][k].append(x)
    o = []
    for i in range(n):
        oi = m.NewBoolVar('o%d' % i)
        a = []
        for S in teams[i]:
            b = m.NewBoolVar('a%d_%d' % (i, len(a)))
            for k in S:
                m.Add(sum(cover[i][k]) >= 1).OnlyEnforceIf(b)
            a.append(b)
        m.Add(sum(a) >= oi)
        o.append(oi)
    m.Maximize(sum(o))
    sol = cp_model.CpSolver()
    sol.parameters.max_deterministic_time = det_time
    sol.parameters.num_workers = WORKERS
    sol.parameters.interleave_search = True
    sol.parameters.random_seed = 0
    st = sol.Solve(m)
    return n if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE) else int(math.floor(sol.BestObjectiveBound() + 1e-6))


def replay(d, res):
    """Global order by CP-SAT start time (ties by index), earliest-start replay with core.evaluate."""
    inst = Inst(d)
    order = sorted(res['start'], key=lambda i: (res['start'][i], i))
    team = {int(i): tuple(S) for i, S in res['team'].items()}
    legal = sorted(team) == list(range(inst.n)) and all(team[i] in inst.teams(i, 'flex') for i in team)
    ev = evaluate(inst, order, team, 0, detail=True)
    delay = max(0, max(ev['comp'][i] - inst.due[i] for i in range(inst.n)))
    return dict(late=ev['n_late'], max_delay_s=delay, legal=legal,
                ok=legal and ev['n_late'] <= res['late'] and ev['n_over'] == 0 and delay <= inst.tmax)


def solve_checked(d, fam, K, det_time, cap_s=CAP_S):
    e = fleet(d, caps_of(fam, K), cap_s)
    res = Capped(e, cap_s).solve(det_time)
    if res['late'] is not None:
        res['replay'] = replay(e, res)
    return res


# ---------------------------------------------------------------- self-checks (trial seeds / toys only)
def _sub(d, idx):
    return dict(d, tasks=[d['tasks'][i] for i in idx], tauE=[[d['tauE'][i][j] for j in idx] for i in idx],
                tauE_start=[[row[j] for j in idx] for row in d['tauE_start']])


def _brute(e):
    """Brute-force enumerator (`paper/code/cpsat/bruteforce.py`) on the cap objective: fewest over-cap blocks,
    then late."""
    sys.path.insert(0, str(ROOT / 'paper' / 'code' / 'cpsat'))
    import bruteforce
    inst = Inst(e)
    b = bruteforce.brute(inst, 0)
    ev = evaluate(inst, b['order'], {i: tuple(S) for i, S in b['team'].items()}, 0)
    return None if ev['n_over'] else ev['n_late']


def selfcheck(det_time=60.0):
    rng = random.Random(20260930)
    slices = sorted((STUDY_ROOT / 'exact' / 'slices').glob('*_s97*.json'))
    assert len(slices) == 24, len(slices)
    load = lambda p: json.loads(p.read_text(encoding='utf8'))
    log, outcome, tight = [], {}, 0
    # 1 enumeration + 3 replay + 4 monotonicity (one extra transporter) on toys
    fleets = ([270, 270], [300, 300], [270, 270, 270], [550, 270], [425, 300], [425, 300, 300], [380, 380], [300, 300, 300])
    for q in range(60):
        d = load(rng.choice(slices))
        sub, caps, cap_s = _sub(d, sorted(rng.sample(range(len(d['tasks'])), rng.choice((4, 5))))), list(rng.choice(fleets)),             rng.choice((1800, 3600, 7200))
        e = fleet(sub, caps, cap_s)
        ex = Capped(e, cap_s).solve(det_time)
        bf = _brute(e)
        assert ex['proven'], ('toy not solved', q, ex['status'])
        assert ex['late'] == bf, ('enumeration', q, ex['late'], bf)
        if bf is not None and ex['route_lb'] is not None:
            assert ex['route_lb'] <= bf, ('route bound above the optimum', q, ex['route_lb'], bf)
            tight += ex['route_lb'] == bf
        if ex['late'] is not None:
            assert replay(e, ex)['ok'], ('replay', q)
        e2 = fleet(sub, caps + caps[-1:], cap_s)
        ex2 = Capped(e2, cap_s).solve(det_time)
        assert ex2['proven'] and (ex['late'] is None or (ex2['late'] is not None and ex2['late'] <= ex['late'])), \
            ('monotonicity', q, ex['late'], ex2['late'])
        outcome[str(ex['late'])] = outcome.get(str(ex['late']), 0) + 1
    say = lambda x: (log.append(x), print(x, flush=True))
    say('1/3/4 enumeration, replay, monotonicity: 60 toys (4-5 blocks, 2-3 transporters, T 30/60/120 min) pass; '
               'fewest late blocks {value: count} = %s (None = no capped schedule); route bound <= optimum in all, '
               'equal in %d' % (dict(sorted(outcome.items())), tight))
    # 2 degeneracy on 7-block sub-slices
    import exact_ontime as XO
    import bounds_cpsat as BOUNDS
    na = nb = 0
    for p in slices:
        d = load(p)
        sub = _sub(d, sorted(rng.sample(range(len(d["tasks"])), 7)))
        for caps in ([550, 550], [550, 550, 550], [300, 300, 300], [425, 300, 300]):
            e = fleet(sub, caps, 10 ** 6)
            a = Capped(e, 10 ** 6).solve(det_time)
            b = XO.OnTime(e).solve(60, workers=8)                     # reference solver: any thread count
            if a['proven'] and a['late'] is not None and b['status'] == 'OPTIMAL':
                assert a['late'] == len(e['tasks']) - b['on_time'], ('T=inf', p.name, caps, a['late'], b['on_time'])
                assert replay(e, a)['ok']
                na += 1
            if min(caps) >= max(t['mass'] for t in sub['tasks']):
                e = fleet(sub, caps, CAP_S)
                c = Capped(e, CAP_S).solve(det_time)
                sol = cp_model.CpSolver()
                sol.parameters.max_time_in_seconds = 60
                sol.parameters.num_workers = 8
                st = sol.Solve(BOUNDS.build(e, CAP_S)[0])
                if c['proven'] and c['late'] is not None and st == cp_model.OPTIMAL:
                    assert c['late'] == len(e['tasks']) - int(round(sol.ObjectiveValue())), ('single carry', p.name, caps)
                    nb += 1
                elif c['status'] == 'INFEASIBLE' or st == cp_model.INFEASIBLE:
                    assert c['status'] == 'INFEASIBLE' and st == cp_model.INFEASIBLE, ('single carry infeasible', p.name, caps)
                    nb += 1
    assert na >= 48 and nb >= 24, (na, nb)
    say('2 degeneracy: T = inf vs exact_ontime agree on %d proven sub-slices; single carry vs bounds_cpsat agree on %d' % (na, nb))
    # determinism: one full trial slice, a budget that ends before the proof and one that proves
    d = load(slices[0])
    rows = []
    for fam, K, budget in (('300', 3, 5.0), ('300', 3, det_time), ('425', 3, det_time), ('MX1', 3, det_time)):
        r = [solve_checked(d, fam, K, budget) for _ in range(3)]
        key = [(x['status'], x['late'], x['late_lb'], x['det_time']) for x in r]
        assert key[0] == key[1] == key[2], ('determinism', fam, K, budget, key)
        rows.append('%s K=%d tau=%g: %s' % (fam, K, budget, key[0]))
    say('determinism (%d worker): status, late count, bound and deterministic time identical in 3 repeats: ' % WORKERS + '; '.join(rows))
    out = STUDY_ROOT / 'results' / 'exact_selfcheck'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'selfcheck.log').write_text('\n'.join(log) + '\n', encoding='utf8')
    print('\n'.join(log))


if __name__ == '__main__':
    if sys.argv[1:2] == ['selfcheck']:
        selfcheck()
