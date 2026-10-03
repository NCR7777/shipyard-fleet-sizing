"""Adaptive large neighbourhood search (ALNS).

Representation: global order `order` + team `team` of each task (as in core.evaluate). Each vehicle executes its
tasks in the order in which they appear in `order`, so the sequences can never wait on each other in a cycle; given
the representation, one forward pass yields all times (a team starts when all members are present, and each vehicle
runs as early as possible).

Insertion evaluation (the core of the repair operators):
  - every rebuild stores "prefix snapshots": before position p, each vehicle's available time and previous task
    and the accumulated objective components;
  - for task i and team S, only positions between tasks of the members of S give different per-vehicle sequences,
    so the candidate positions are {0} ∪ {position of a member task + 1}, pruned by a time window (member
    available time no later than d_i + win, successor start no earlier than r_i − win);
  - screening: exact cost of the inserted task itself + first-order effect on the next task of each member
    (change of empty travel, and of tardiness and waiting caused by the delay);
  - verification: the best M candidates of the screening are simulated exactly from the snapshot to the end, and
    the best one is taken.
  - candidate vehicles: the first Kc vehicles ranked by "earliest start when doing i alone" (with flexible
    coupling, plus the 2 best vehicles able to carry i alone); minimal teams are enumerated among the candidate
    vehicles, adding vehicles one at a time while there is none.

Destroy operators: random, worst cost (tardiness and waiting), related (Shaw: start time + empty travel distance +
          shared vehicles), team break (removes coupled tasks), single-vehicle route; mode operators (flexible
          coupling only): coupled -> one heavy vehicle, single vehicle -> coupled light vehicles (the selected tasks
          are restricted to that mode during repair; the rest is filled by related removal).
Repair operators: greedy (random order), greedy (by release time), regret-2 (ranked by screening value, the chosen
          insertion verified exactly).
Acceptance: simulated annealing with geometric cooling; operator weights adapt per segment (scores 33/9/13 of
Ropke & Pisinger 2006).
"""
import bisect
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
from core import evaluate, minimal_teams, lam_eff, tard_cost   # noqa: E402
from baselines import greedy_append, _append_eval   # noqa: E402

DEFAULT = dict(
    max_iter=5000, time_limit=60.0,
    q_min_frac=0.05, q_max_frac=0.3, q_min=2, q_max=30,
    Kc=5, M=3, win_s=3 * 3600,
    segment=100, reaction=0.1, sigma=(33, 9, 13),
    sa_worse=0.05, sa_p=0.5, sa_end_ratio=1e-3,
    p_worst=3.0, p_shaw=6.0, shaw_w=(1.0, 1.0, 0.5),
    mode_frac=0.25,
    parity=False,   # True: Rigid and Flex use the same destroy operators and candidate-vehicle rule (symmetric runs)
    # Optional extensions; with both switched off the search is the basic ALNS, bit for bit
    n_construct=0,  # number N_c of randomised chronological greedy constructions (a count, reproducible); 0 = off
    chrono=False,   # True: add the "chronological rebuild" to the repair operators
    rg_noise_min=(0, 10, 30, 60),            # construction/rebuild: upper bound of uniform release noise (min)
    rg_lam_team=(0.0, 0.03, 0.1, 0.3, 1.0),  # construction/rebuild: labour weight when choosing a team
)


class Sched:
    """A (possibly incomplete) solution with its simulated times and prefix snapshots."""

    def __init__(self, inst, lam, order, team):
        self.inst, self.lam = inst, lam_eff(lam)   # λ = 0 becomes LEX_EPS (lexicographic objective)
        self.order = list(order)
        self.team = dict(team)
        self.rebuild()

    def rebuild(self):
        inst, K = self.inst, self.inst.K
        tE0, tE, rel, due, D, dl = inst.tE0, inst.tE, inst.rel, inst.due, inst.D, inst.dl
        wc = self.lam * inst.crew
        avail = [0] * K
        last = [-1] * K
        ct = inst.crew_team
        tard = empty = sync = service = svc_crew = 0
        sa, sl, sacc = [], [], []
        start, comp, arrive, contrib = {}, {}, {}, {}
        seqs = [[] for _ in range(K)]
        seqpos = [[] for _ in range(K)]
        pos = {}
        for p, i in enumerate(self.order):
            sa.append(avail[:])
            sl.append(last[:])
            sacc.append((tard, empty, sync, service, svc_crew))
            S = self.team[i]
            r = rel[i]
            s = r
            arr = []
            e_i = 0
            for k in S:
                t = tE0[k][i] if last[k] < 0 else tE[last[k]][i]
                a = avail[k] + t
                e_i += t
                arr.append(a)
                if a > s:
                    s = a
            w_i = 0
            for a in arr:
                w_i += s - (a if a > r else r)
            dd = D[i] + (dl[i] if len(S) > 1 else 0)
            c = s + dd
            t_i = tard_cost(inst, c - due[i])
            for k in S:
                avail[k] = c
                last[k] = i
                seqs[k].append(i)
                seqpos[k].append(p)
            tard += t_i
            empty += e_i
            sync += w_i
            service += len(S) * dd
            if ct is not None:
                svc_crew += ct[len(S)] * dd
            start[i], comp[i], pos[i] = s, c, p
            arrive[i] = arr
            contrib[i] = t_i + wc * (e_i + w_i)
        sa.append(avail[:])
        sl.append(last[:])
        sacc.append((tard, empty, sync, service, svc_crew))
        self.snap_avail, self.snap_last, self.snap_acc = sa, sl, sacc
        self.start, self.comp, self.arrive, self.contrib = start, comp, arrive, contrib
        self.seqs, self.seqpos, self.pos = seqs, seqpos, pos
        self.tard, self.empty, self.sync, self.service = tard, empty, sync, service
        self.work = empty + sync + service
        if ct is None:
            self.obj = tard + wc * self.work
        else:
            self.obj = tard + self.lam * (inst.crew * (empty + sync) + svc_crew)

    # ---------- insertion evaluation ----------
    def _tin(self, k, prev, i):
        return self.inst.tE0[k][i] if prev < 0 else self.inst.tE[prev][i]

    def _next_of(self, k, p):
        q = bisect.bisect_left(self.seqpos[k], p)
        return self.seqs[k][q] if q < len(self.seqs[k]) else -1

    def vehicle_scores(self, i):
        """For each vehicle: earliest start when doing i alone (best over its insertion positions), plus the delay
        this pushes onto the successor."""
        inst = self.inst
        r, Di = inst.rel[i], inst.D[i]
        out = []
        for k in range(inst.K):
            best = math.inf
            slots = [0] + [x + 1 for x in self.seqpos[k]]
            for p in slots:
                av = self.snap_avail[p][k]
                s = av + self._tin(k, self.snap_last[p][k], i)
                if s < r:
                    s = r
                j = self._next_of(k, p)
                push = 0
                if j >= 0:
                    push = s + Di + inst.tE[i][j] - self.start[j]
                    if push < 0:
                        push = 0
                v = s + push
                if v < best:
                    best = v
            out.append(best)
        return out

    def teams_for(self, i, mode, Kc, parity=False):
        inst = self.inst
        m = inst.mass[i]
        cap = inst.cap
        over = inst.maxcap < m
        sc = self.vehicle_scores(i)
        if mode == 'single' or (mode == 'rigid' and not over):
            pool = [k for k in range(inst.K) if cap[k] >= m]
            eff = 'single'
        elif mode == 'multi' or (mode == 'rigid' and over):
            pool = [k for k in range(inst.K) if cap[k] < m]
            eff = 'multi'
        else:
            pool = list(range(inst.K))
            eff = 'flex'
        pool.sort(key=lambda k: (sc[k], k))
        cand = pool[:Kc]
        if eff == 'flex' or (parity and eff == 'single'):
            extra = [k for k in pool if cap[k] >= m and k not in cand][:2]
            cand = cand + extra
        nxt = Kc
        while True:
            teams = minimal_teams(cap, m, eff, inst.max_team, sorted(cand),
                                  same_capacity_only=inst.same_capacity_only)
            if teams or nxt >= len(pool):
                return teams, set(cand)
            cand = cand + [k for k in pool[nxt:nxt + 1] if k not in cand]
            nxt += 1

    def positions(self, i, S, win):
        inst = self.inst
        P = {0}
        for k in S:
            for x in self.seqpos[k]:
                P.add(x + 1)
        P = sorted(P)
        lo, hi = inst.rel[i] - win, inst.due[i] + win
        keep = []
        for p in P:
            ok = True
            for k in S:
                if self.snap_avail[p][k] > hi:
                    ok = False
                    break
                j = self._next_of(k, p)
                if j >= 0 and self.start[j] < lo:
                    ok = False
                    break
            if ok:
                keep.append(p)
        return keep if keep else P

    def screen(self, i, S, p):
        """Estimated objective increment of inserting (i, S, p)."""
        inst = self.inst
        wc = self.lam * inst.crew
        r = inst.rel[i]
        av, ls = self.snap_avail[p], self.snap_last[p]
        s = r
        arr = []
        emp = 0
        for k in S:
            t = self._tin(k, ls[k], i)
            a = av[k] + t
            emp += t
            arr.append(a)
            if a > s:
                s = a
        w = 0
        for a in arr:
            w += s - (a if a > r else r)
        dd = inst.D[i] + (inst.dl[i] if len(S) > 1 else 0)
        c = s + dd
        if inst.crew_team is None:
            cost = tard_cost(inst, c - inst.due[i]) + wc * (emp + w + len(S) * dd)
        else:
            cost = (tard_cost(inst, c - inst.due[i]) + wc * (emp + w)
                    + self.lam * inst.crew_team[len(S)] * dd)
        # first-order effect on the next task of each member
        nexts = {}
        for k in S:
            j = self._next_of(k, p)
            if j < 0:
                continue
            old_in = self._tin(k, ls[k], j)
            new_in = inst.tE[i][j]
            cost += wc * (new_in - old_in)
            nexts.setdefault(j, []).append((k, c + new_in))
        for j, lst in nexts.items():
            S_j = self.team[j]
            old_s = self.start[j]
            new_a = dict(lst)
            new_s = old_s
            for _, a in lst:
                if a > new_s:
                    new_s = a
            ds = new_s - old_s
            rj = inst.rel[j]
            dw = 0
            for k, a_old in zip(S_j, self.arrive[j]):
                a_new = new_a.get(k, a_old)
                dw += (new_s - (a_new if a_new > rj else rj)) - (old_s - (a_old if a_old > rj else rj))
            cj = self.comp[j]
            dj = inst.due[j]
            dt = tard_cost(inst, cj + ds - dj) - tard_cost(inst, cj - dj)
            cost += dt + wc * dw
        return cost

    def exact(self, i, S, p):
        """Exact objective after inserting (i, S, p), simulated from snapshot p."""
        inst = self.inst
        tE0, tE, rel, due, D, dl = inst.tE0, inst.tE, inst.rel, inst.due, inst.D, inst.dl
        avail = self.snap_avail[p][:]
        last = self.snap_last[p][:]
        tard, empty, sync, service, svc_crew = self.snap_acc[p]
        ct = inst.crew_team
        team = self.team
        seq = [i] + self.order[p:]
        for j in seq:
            SS = S if j == i else team[j]
            r = rel[j]
            s = r
            arr = []
            for k in SS:
                t = tE0[k][j] if last[k] < 0 else tE[last[k]][j]
                a = avail[k] + t
                empty += t
                arr.append(a)
                if a > s:
                    s = a
            for a in arr:
                sync += s - (a if a > r else r)
            dd = D[j] + (dl[j] if len(SS) > 1 else 0)
            c = s + dd
            service += len(SS) * dd
            if ct is not None:
                svc_crew += ct[len(SS)] * dd
            for k in SS:
                avail[k] = c
                last[k] = j
            if c > due[j]:
                tard += tard_cost(inst, c - due[j])
        if ct is None:
            return tard + self.lam * inst.crew * (empty + sync + service)
        return tard + self.lam * (inst.crew * (empty + sync) + svc_crew)

    def candidates(self, i, mode, cfg):
        teams, veh = self.teams_for(i, mode, cfg['Kc'], cfg.get('parity', False))
        out = []
        for S in teams:
            for p in self.positions(i, S, cfg['win_s']):
                out.append((self.screen(i, S, p), p, S))
        out.sort(key=lambda x: (x[0], x[1], x[2]))
        return out, veh

    def best_exact(self, i, cands, M):
        best = None
        for sc, p, S in cands[:M]:
            v = self.exact(i, S, p)
            if best is None or v < best[0] - 1e-9:
                best = (v, p, S)
        return best

    def insert(self, i, S, p):
        self.order.insert(p, i)
        self.team[i] = tuple(S)
        self.rebuild()

    def copy_without(self, removed):
        rs = set(removed)
        return Sched(self.inst, self.lam, [t for t in self.order if t not in rs],
                     {t: S for t, S in self.team.items() if t not in rs})


# ---------- destroy operators ----------
def _pick_skewed(rng, lst, p):
    return lst[int(len(lst) * (rng.random() ** p))]


def d_random(sol, q, rng, cfg, mode):
    return [(t, None) for t in rng.sample(sol.order, min(q, len(sol.order)))]


def d_worst(sol, q, rng, cfg, mode):
    ranked = sorted(sol.order, key=lambda t: -sol.contrib[t])
    out = []
    while len(out) < q and ranked:
        t = _pick_skewed(rng, ranked, cfg['p_worst'])
        ranked.remove(t)
        out.append(t)
    return [(t, None) for t in out]


def _related_fill(sol, seeds, q, rng, cfg):
    inst = sol.inst
    w1, w2, w3 = cfg['shaw_w']
    span = max(1.0, max(sol.start.values()) - min(sol.start.values())) if sol.start else 1.0
    tnorm = span / 4.0
    enorm = max(1.0, cfg['_mean_tE'])
    chosen = list(seeds)
    rest = [t for t in sol.order if t not in set(chosen)]
    if not chosen and rest:
        t0 = rng.choice(rest)
        chosen.append(t0)
        rest.remove(t0)
    while len(chosen) < q and rest:
        ref = rng.choice(chosen)
        sref = set(sol.team[ref])

        def rel(t):
            dt = abs(sol.start[t] - sol.start[ref]) / tnorm
            dd = (inst.tE[ref][t] + inst.tE[t][ref]) / (2 * enorm)
            share = 0.0 if sref & set(sol.team[t]) else 1.0
            return w1 * dt + w2 * dd + w3 * share
        rest.sort(key=rel)
        t = _pick_skewed(rng, rest, cfg['p_shaw'])
        rest.remove(t)
        chosen.append(t)
    return chosen


def d_related(sol, q, rng, cfg, mode):
    return [(t, None) for t in _related_fill(sol, [], q, rng, cfg)]


def d_team_break(sol, q, rng, cfg, mode):
    coop = [t for t in sol.order if len(sol.team[t]) > 1]
    if not coop:
        return d_random(sol, q, rng, cfg, mode)
    if len(coop) > q:
        coop = rng.sample(coop, q)
    return [(t, None) for t in _related_fill(sol, coop, q, rng, cfg)]


def d_route(sol, q, rng, cfg, mode):
    used = [k for k in range(sol.inst.K) if sol.seqs[k]]
    if not used:
        return d_random(sol, q, rng, cfg, mode)
    k = rng.choice(used)
    tasks = list(sol.seqs[k])
    if len(tasks) > cfg['_q_hi']:
        tasks = rng.sample(tasks, cfg['_q_hi'])
    return [(t, None) for t in tasks]


def d_to_single(sol, q, rng, cfg, mode):
    inst = sol.inst
    el = [t for t in sol.order if len(sol.team[t]) > 1 and inst.mass[t] <= inst.maxcap]
    if not el:
        return d_random(sol, q, rng, cfg, mode)
    tg = rng.sample(el, min(len(el), max(1, int(q * cfg['mode_frac']))))
    rest = [t for t in _related_fill(sol, tg, q, rng, cfg) if t not in tg]
    return [(t, 'single') for t in tg] + [(t, None) for t in rest]


def d_to_team(sol, q, rng, cfg, mode):
    inst = sol.inst
    el = [t for t in sol.order if len(sol.team[t]) == 1 and inst.teams(t, 'multi')]
    if not el:
        return d_random(sol, q, rng, cfg, mode)
    tg = rng.sample(el, min(len(el), max(1, int(q * cfg['mode_frac']))))
    rest = [t for t in _related_fill(sol, tg, q, rng, cfg) if t not in tg]
    return [(t, 'multi') for t in tg] + [(t, None) for t in rest]


DESTROY_COMMON = [('random', d_random), ('worst', d_worst), ('related', d_related),
                  ('team_break', d_team_break), ('route', d_route)]
DESTROY_FLEX = [('to_single', d_to_single), ('to_team', d_to_team)]


# ---------- repair operators ----------
def _mode_of(forced, mode):
    return forced if (forced and mode == 'flex') else mode


def r_greedy(sol, removed, rng, cfg, mode, by_release=False):
    items = list(removed)
    if by_release:
        items.sort(key=lambda x: (sol.inst.rel[x[0]], sol.inst.due[x[0]], x[0]))
    else:
        rng.shuffle(items)
    for t, forced in items:
        cands, _ = sol.candidates(t, _mode_of(forced, mode), cfg)
        v, p, S = sol.best_exact(t, cands, cfg['M'])
        sol.insert(t, S, p)
    return sol


def r_greedy_rel(sol, removed, rng, cfg, mode):
    return r_greedy(sol, removed, rng, cfg, mode, by_release=True)


def r_regret2(sol, removed, rng, cfg, mode):
    pending = dict(removed)
    cache = {}
    changed = None
    while pending:
        for t, forced in pending.items():
            if t in cache and changed is not None and not (cache[t][2] & changed):
                continue
            cands, veh = sol.candidates(t, _mode_of(forced, mode), cfg)
            b1 = cands[0][0]
            b2 = cands[1][0] if len(cands) > 1 else b1 + 1e12
            cache[t] = (b1, b2, veh | {k for _, _, S in cands[:cfg['M']] for k in S})
        t = max(pending, key=lambda x: (cache[x][1] - cache[x][0], -cache[x][0], -x))
        forced = pending.pop(t)
        cache.pop(t)
        cands, _ = sol.candidates(t, _mode_of(forced, mode), cfg)
        v, p, S = sol.best_exact(t, cands, cfg['M'])
        old = dict(sol.comp)
        sol.insert(t, S, p)
        changed = set(S)
        for j, cj in old.items():
            if sol.comp[j] != cj:
                changed |= set(sol.team[j])
    return sol


def _pick_team(inst, i, mode_eff, lam_team, avail, last):
    """Choose a team from the admissible set of this mode by incremental cost (labour weight lam_team); ties go
    to earlier completion, then fewer vehicles, then smaller indices."""
    best = None
    for S in inst.teams(i, mode_eff):
        cost, s, c, _ = _append_eval(inst, lam_team, avail, last, i, S)
        key = (cost, c, len(S), S)
        if best is None or key < best[0]:
            best = (key, S, c)
    return best[1], best[2]


def _chrono_append(inst, seq, team_fixed, forced, mode, lam_team):
    """Append all tasks once in the given sequence: tasks in team_fixed keep their team, the others choose a team
    by incremental cost."""
    avail = [0] * inst.K
    last = [-1] * inst.K
    team = {}
    for i in seq:
        if i in team_fixed:
            S = team_fixed[i]
            _, s, c, _ = _append_eval(inst, lam_team, avail, last, i, S)
        else:
            S, c = _pick_team(inst, i, _mode_of(forced.get(i), mode), lam_team, avail, last)
        for k in S:
            avail[k] = c
            last[k] = i
        team[i] = S
    return list(seq), team


def construct_rgreedy(inst, lam, mode, cfg, rng):
    """Randomised chronological greedy: each pass sorts the tasks by (release time + U(0, noise), due time, task
    index), drawing the noise bound and the labour weight for team choice at random from the candidate values;
    passes are evaluated with the λ of this run and the best is returned.
    Teams are chosen only from the admissible set of this mode; on a homogeneous fleet both modes have the same
    admissible sets, so the same seed gives the same construction."""
    best = None
    for _ in range(cfg['n_construct']):
        noise = 60 * rng.choice(cfg['rg_noise_min'])
        lt = rng.choice(cfg['rg_lam_team'])
        key = {i: (inst.rel[i] + rng.uniform(0, noise), inst.due[i], i) for i in range(inst.n)}
        seq = sorted(range(inst.n), key=lambda i: key[i])
        o, t = _chrono_append(inst, seq, {}, {}, mode, lt)
        s = Sched(inst, lam, o, t)
        if best is None or s.obj < best.obj - 1e-9:
            best = s
    return best


def r_chrono(sol, removed, rng, cfg, mode):
    """Chronological rebuild: retained tasks keep their teams and are ordered by their current start times;
    removed tasks are merged into this order by (release time + noise) and choose a team by incremental cost (with
    one randomly drawn labour weight); then all tasks are appended again in this chronological order."""
    inst = sol.inst
    noise = 60 * rng.choice(cfg['rg_noise_min'])
    lt = rng.choice(cfg['rg_lam_team'])
    forced = dict(removed)
    key = {i: (sol.start[i], 0, i) for i in sol.order}
    for i in forced:
        key[i] = (inst.rel[i] + rng.uniform(0, noise), 1, i)
    seq = sorted(key, key=lambda i: key[i])
    fixed = {i: tuple(sol.team[i]) for i in sol.order}
    o, t = _chrono_append(inst, seq, fixed, forced, mode, lt)
    sol.order = o
    sol.team = t
    sol.rebuild()
    return sol


REPAIR = [('greedy', r_greedy), ('greedy_rel', r_greedy_rel), ('regret2', r_regret2)]
REPAIR_V2 = REPAIR + [('chrono', r_chrono)]


def construct_regret(inst, lam, mode, cfg, rng):
    sol = Sched(inst, lam, [], {})
    return r_regret2(sol, [(t, None) for t in range(inst.n)], rng, cfg, mode)


def _roulette(rng, w):
    x = rng.random() * sum(w)
    for idx, v in enumerate(w):
        x -= v
        if x <= 0:
            return idx
    return len(w) - 1


def _snap(inst, lam, sched, it, t0):
    """Metrics of the incumbent at a checkpoint (read-only)."""
    ev = evaluate(inst, sched.order, sched.team, lam, detail=True)
    late = [ev['comp'][i] - inst.due[i] for i in range(inst.n)]
    return dict(it=it, wall=round(time.time() - t0, 2), obj=sched.obj, on_time=sum(x <= 0 for x in late),
                max_tard=max(0, max(late)), crew_s=ev['crew_s'], n_over=ev.get('n_over', 0))


def alns(inst, lam, mode='flex', seed=0, cfg=None, init=None, log_every=0, check=False, init_extra=None,
         checkpoints=()):
    """Return the best solution and the search record. mode: flex (ALNS-Flex) / rigid (ALNS-Rigid).
    init_extra: additional initial solutions [(order, team), ...]; the best of these and the constructed solutions
    is the starting point (for example, Flex started from the Rigid solution is by construction no worse than it;
    the solutions must be feasible under this mode)."""
    c = dict(DEFAULT)
    if cfg:
        c.update(cfg)
    rng = random.Random(seed)
    n = inst.n
    c['_mean_tE'] = sum(inst.tE[i][j] for i in range(n) for j in range(n) if i != j) / max(1, n * (n - 1))
    q_lo = max(c['q_min'], int(round(c['q_min_frac'] * n)))
    q_hi = max(q_lo, min(c['q_max'], int(round(c['q_max_frac'] * n))))
    q_hi = min(q_hi, n)
    q_lo = min(q_lo, q_hi)
    c['_q_hi'] = q_hi
    t0 = time.time()
    # initial solution: the better of greedy append and regret-2 construction under the same rule
    if init is None:
        g = greedy_append(inst, lam, mode)
        s_g = Sched(inst, lam, g['order'], g['team'])
        s_r = construct_regret(inst, lam, mode, c, rng)
        cur = s_g if s_g.obj <= s_r.obj else s_r
        init_src = 'greedy' if cur is s_g else 'regret2'
        if c['n_construct'] > 0:
            s_rg = construct_rgreedy(inst, lam, mode, c, random.Random(seed * 7919 + 17))
            if s_rg.obj < cur.obj - 1e-9:
                cur, init_src = s_rg, 'rgreedy'
    else:
        cur = Sched(inst, lam, init[0], {int(i): tuple(S) for i, S in init[1].items()})
        init_src = 'given'
    for q, (o_x, t_x) in enumerate(init_extra or []):
        t_x = {int(i): tuple(S) for i, S in t_x.items()}
        for i, S in t_x.items():
            if tuple(S) not in inst.teams(i, mode):
                raise ValueError('init_extra[%d]: task %d, team %s is infeasible under %s' % (q, i, S, mode))
        s_x = Sched(inst, lam, o_x, t_x)
        if s_x.obj < cur.obj - 1e-9:
            cur, init_src = s_x, 'extra%d' % q
    best = cur
    obj0 = cur.obj
    destroy = DESTROY_COMMON + (DESTROY_FLEX if (mode == 'flex' or c.get('parity')) else [])
    dw = [1.0] * len(destroy)
    repair = REPAIR_V2 if c['chrono'] else REPAIR
    rw = [1.0] * len(repair)
    ds = [0.0] * len(destroy); dn = [0] * len(destroy)
    rs = [0.0] * len(repair); rn = [0] * len(repair)
    T0 = c['sa_worse'] * max(obj0, 1.0) / (-math.log(c['sa_p']))
    alpha = c['sa_end_ratio'] ** (1.0 / max(1, c['max_iter']))
    T = T0
    seen = set()
    trace = []
    it = 0
    snaps = [_snap(inst, lam, best, 0, t0)] if 0 in checkpoints else []
    while it < c['max_iter'] and time.time() - t0 < c['time_limit']:
        it += 1
        q = rng.randint(q_lo, q_hi)
        di = _roulette(rng, dw)
        ri = _roulette(rng, rw)
        removed = destroy[di][1](cur, q, rng, c, mode)
        new = cur.copy_without([t for t, _ in removed])
        repair[ri][1](new, removed, rng, c, mode)
        if check:
            ev = evaluate(inst, new.order, new.team, lam)
            assert abs(ev['obj'] - new.obj) <= 1e-6 * max(1, new.obj), (ev['obj'], new.obj)
            assert len(new.order) == n
        key = (tuple(new.order), tuple(sorted(new.team.items())))
        score = 0
        if new.obj < best.obj - 1e-9:
            best = new
            cur = new
            score = c['sigma'][0]
        elif new.obj < cur.obj - 1e-9:
            cur = new
            if key not in seen:
                score = c['sigma'][1]
        elif rng.random() < math.exp(-(new.obj - cur.obj) / max(T, 1e-12)):
            cur = new
            if key not in seen:
                score = c['sigma'][2]
        seen.add(key)
        ds[di] += score; dn[di] += 1
        rs[ri] += score; rn[ri] += 1
        T *= alpha
        if it % c['segment'] == 0:
            for a in range(len(dw)):
                if dn[a]:
                    dw[a] = dw[a] * (1 - c['reaction']) + c['reaction'] * ds[a] / dn[a]
                dw[a] = max(dw[a], 0.05)
            for a in range(len(rw)):
                if rn[a]:
                    rw[a] = rw[a] * (1 - c['reaction']) + c['reaction'] * rs[a] / rn[a]
                rw[a] = max(rw[a], 0.05)
            ds = [0.0] * len(destroy); dn = [0] * len(destroy)
            rs = [0.0] * len(repair); rn = [0] * len(repair)
        if it in checkpoints:
            snaps.append(_snap(inst, lam, best, it, t0))
        if log_every and it % log_every == 0:
            trace.append((it, round(time.time() - t0, 2), cur.obj, best.obj))
            print('it=%d t=%.1fs cur=%.1f best=%.1f' % trace[-1], flush=True)
    wall = time.time() - t0
    ev = evaluate(inst, best.order, best.team, lam)
    assert abs(ev['obj'] - best.obj) <= 1e-6 * max(1, best.obj)
    # Note: with λ = 0 the returned obj is tardiness + LEX_EPS·person-seconds
    return dict(obj=best.obj, order=best.order, team={int(i): list(S) for i, S in best.team.items()},
                tard=ev['tard'], work=ev['work'], empty=ev['empty'], sync=ev['sync'], service=ev['service'],
                n_coop=ev['n_coop'], iters=it, wall_s=wall, init_obj=obj0, init_src=init_src, mode=mode,
                seed=seed, lam=lam, weights_destroy=dict(zip([d[0] for d in destroy], [round(x, 3) for x in dw])),
                weights_repair=dict(zip([r[0] for r in repair], [round(x, 3) for x in rw])), trace=trace,
                checkpoints=snaps)

# ---------- exact accelerations ----------
# Results are identical to the base search (same teams, orders, objective values and checkpoints); the proof
# sketches are in fastpick.py and fastcand.py.
import fastpick as _fastpick   # noqa: E402
import fastcand as _fastcand   # noqa: E402
_pick_team = _fastpick.pick_team
Sched.candidates = _fastcand.candidates
