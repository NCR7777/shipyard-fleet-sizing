"""Shared core of the scheduling model: instance loading, admissible teams, forward evaluation.

An instance is a solver-independent JSON file (all times in integer seconds) generated from the main shipyard map:
    tasks[i]    : release, due, load, unload, tauL (loaded travel time from pickup to drop-off), mass ...
    vehicles[k] : cap (rated capacity, t), start (start location)
    tauE_start  : K x n, empty travel time of vehicle k from its start to the pickup of task i
    tauE        : n x n, empty travel time from the drop-off of task i to the pickup of task j
    meta        : scenario parameters such as delta_s (coupling alignment time), crew (crew per vehicle)
                  and max_team (largest team size)

Objective:
    obj = Σ_i T_i + λ · crew · Σ_k (empty travel + synchronisation wait + handling + loaded travel + alignment)
    T_i = max(0, c_i − due_i);  c_i = s_i + δ·[|S_i| > 1] + load_i + tauL_i + unload_i
    s_i = max(r_i, latest arrival among the team members); a member leaves empty for the pickup as soon as it
    finishes its previous task (earliest execution), and members that arrive first wait at the pickup;
    synchronisation wait = s_i − max(a_ik, r_i); waiting for the task to be released is not counted.

Crew rule (meta['crew_team'], optional):
    default (per vehicle): crew persons per vehicle, so a team working jointly uses crew × team size persons,
    as in the formula above;
    with crew_team = {team size: persons}: empty travel and synchronisation wait still count crew persons per
    vehicle, while joint work (δ + load + travel + unload) counts crew_team[|S|] persons. For example, a Goldhofer
    sample describes a coupled team as "usually requiring only one operator", which gives {1: 4, 2: 4, 3: 4}.
    General objective:
        obj = Σ T_i + λ·[crew·Σ(empty travel + sync wait) + Σ_i crew_team[|S_i|]·(δ·[|S_i|>1] + D_i)]

Global-order representation: a solution = (global order `order`, team `team` of each task). Each vehicle executes
its tasks in the order in which they appear in `order`. Any per-vehicle sequences without a circular wait
correspond to at least one global order (a topological order), so the representation loses no solution; for given
sequences, the earliest-start timetable is optimal for this objective (neither tardiness nor the counted waiting
can decrease by starting later).
"""
import itertools
import json

INF = float('inf')
# With λ = 0 the objective is lexicographic, tardiness first and labour second: obj = tardiness + LEX_EPS·person-s.
# Tardiness is in whole seconds; with person-s < 1e7, LEX_EPS·person-s < 0.1 s cannot change the tardiness ranking.
LEX_EPS = 1e-8


def lam_eff(lam):
    return LEX_EPS if lam == 0 else lam


class Inst:
    def __init__(self, d):
        self.raw = d
        self.name = d['name']
        T, V = d['tasks'], d['vehicles']
        self.n, self.K = len(T), len(V)
        self.ids = [t['id'] for t in T]
        self.mass = [t['mass'] for t in T]
        self.rel = [t['release'] for t in T]
        self.due = [t['due'] for t in T]
        self.load = [t['load'] for t in T]
        self.unload = [t['unload'] for t in T]
        self.tauL = [t['tauL'] for t in T]
        self.D = [t['load'] + t['tauL'] + t['unload'] for t in T]
        self.cap = [v['cap'] for v in V]
        self.tE0 = d['tauE_start']
        self.tE = d['tauE']
        m = d['meta']
        self.delta = m['delta_s']
        # Per-task alignment time: δ_i = δ + Δτ × number of turns of at least 60° on the loaded path;
        # Δτ (meta['delta_turn_s']) defaults to 0, in which case δ_i = δ
        dtau = m.get('delta_turn_s', 0) or 0
        self.dl = [self.delta + dtau * t.get('turns', 0) for t in T]
        self.crew = m['crew']
        self.max_team = m['max_team']
        ct = m.get('crew_team')
        # crew_team[s]: persons when s vehicles work jointly; None means crew persons per vehicle (default rule)
        self.crew_team = None if ct is None else {int(k): v for k, v in ct.items()}
        if self.crew_team is not None:
            missing = [s for s in range(1, self.max_team + 1) if s not in self.crew_team]
            if missing:
                raise ValueError('crew_team is missing team sizes %s' % missing)
        # Every admissible minimal team is a singleton in this case. Use one
        # arithmetic branch for mathematically identical crew rules so rounding
        # cannot perturb neighbourhood tie ordering in the negative control.
        if (self.crew_team is not None and self.crew_team[1] == self.crew
                and min(self.cap) >= max(self.mass)):
            self.crew_team = None
        self.maxcap = max(self.cap)
        self.same_capacity_only = bool(m.get('same_capacity_only', False))
        self.objective_mode = m.get('objective_mode', 'tard')
        # A schedule can be serialised within this horizon. One late-task
        # penalty exceeds the maximum possible sum of tardiness in that horizon.
        horizon = max(self.rel) + sum(
            self.D[i] + self.dl[i] +
            max([self.tE0[k][i] for k in range(self.K)] +
                [self.tE[j][i] for j in range(self.n) if j != i])
            for i in range(self.n))
        self.late_penalty = self.n * horizon + 1 if self.objective_mode in ('service', 'cap') else 0
        # 'cap' mode: a delay cap T_max (meta['tmax_s']) takes priority over the late count;
        # one block beyond the cap outweighs every late-count and tardiness difference.
        self.tmax = m.get('tmax_s') if self.objective_mode == 'cap' else None
        self.cap_penalty = (self.n + 1) * self.late_penalty if self.tmax is not None else 0
        self._teams = {}

    def crew_of(self, size):
        """Number of persons when `size` vehicles work jointly."""
        return self.crew * size if self.crew_team is None else self.crew_team[size]

    def teams(self, i, mode):
        """All admissible teams for task i over the whole fleet (mode: flex / rigid / single / multi)."""
        key = (i, mode)
        if key not in self._teams:
            self._teams[key] = minimal_teams(self.cap, self.mass[i], mode, self.max_team,
                                            same_capacity_only=self.same_capacity_only)
        return self._teams[key]


def load_instance(path):
    with open(path, encoding='utf-8') as f:
        return Inst(json.load(f))


def minimal_teams(cap, m, mode, max_team, cand=None, same_capacity_only=False):
    """Admissible teams: single vehicles {k: Q_k ≥ m} and minimal multi-vehicle teams (Σ Q ≥ m, and removing any
    member makes the team insufficient; |S| ≤ max_team).

    mode:
      flex   -- single vehicles and minimal multi-vehicle teams (flexible coupling, this paper);
      rigid  -- couple only when overweight (the rule of Jiang 2021): single vehicles whenever some vehicle of the
                fleet can carry the block alone, otherwise minimal multi-vehicle teams;
      single -- single vehicles only; multi -- minimal multi-vehicle teams only (used by the mode operators).
    cand: combine only these vehicles (the ALNS candidate vehicles); for rigid, "overweight" is still judged on the
    whole fleet.
    """
    ks = range(len(cap)) if cand is None else cand
    singles = [(k,) for k in ks if cap[k] >= m]
    overweight = max(cap) < m
    if mode == 'single' or (mode == 'rigid' and not overweight):
        return singles
    light = sorted(k for k in ks if cap[k] < m)
    multi = []
    for size in range(2, max_team + 1):
        for c in itertools.combinations(light, size):
            if same_capacity_only and len({cap[k] for k in c}) > 1:
                continue
            s = sum(cap[k] for k in c)
            if s >= m and s - min(cap[k] for k in c) < m:
                multi.append(c)
    if mode in ('multi', 'rigid'):
        return multi
    if mode == 'flex':
        return singles + multi
    raise ValueError(mode)


def tard_cost(inst, lateness):
    """Search score for one task; physical tardiness is reported separately."""
    return (max(0, lateness) + (inst.late_penalty if lateness > 0 else 0)
            + (inst.cap_penalty if inst.tmax is not None and lateness > inst.tmax else 0))


def evaluate(inst, order, team, lam, detail=False):
    """Simulate forward in the global order. Returns the objective and its components (seconds); with
    detail=True also the per-task times and the per-vehicle sequences."""
    K = inst.K
    avail = [0] * K
    last = [-1] * K
    tE0, tE, rel, due, D, dl = inst.tE0, inst.tE, inst.rel, inst.due, inst.D, inst.dl
    tard = empty = sync = service = n_late = n_over = 0
    svc_crew = 0            # person-seconds of joint work (used only when crew_team is given)
    n_coop = 0
    if detail:
        start, comp, arrive = {}, {}, {}
        seqs = [[] for _ in range(K)]
    for i in order:
        S = team[i]
        r = rel[i]
        s = r
        arr = []
        for k in S:
            t = tE0[k][i] if last[k] < 0 else tE[last[k]][i]
            a = avail[k] + t
            empty += t
            arr.append(a)
            if a > s:
                s = a
        for a in arr:
            sync += s - (a if a > r else r)
        dd = D[i] + (dl[i] if len(S) > 1 else 0)
        if len(S) > 1:
            n_coop += 1
        c = s + dd
        service += len(S) * dd
        if inst.crew_team is not None:
            svc_crew += inst.crew_team[len(S)] * dd
        for k in S:
            avail[k] = c
            last[k] = i
        if c > due[i]:
            tard += c - due[i]
            n_late += 1
            if inst.tmax is not None and c - due[i] > inst.tmax:
                n_over += 1
        if detail:
            start[i], comp[i], arrive[i] = s, c, dict(zip(S, arr))
            for k in S:
                seqs[k].append(i)
    work = empty + sync + service
    if inst.crew_team is None:
        crew_s = inst.crew * work
    else:
        crew_s = inst.crew * (empty + sync) + svc_crew
    out = dict(obj=tard + inst.late_penalty * n_late + inst.cap_penalty * n_over + lam_eff(lam) * crew_s,
               n_late=n_late, n_over=n_over, tard=tard, work=work, crew_s=crew_s, empty=empty, sync=sync,
               service=service, n_coop=n_coop)
    if detail:
        out.update(start=start, comp=comp, arrive=arrive, seqs=seqs)
    return out


def load_index(caps, masses, D, delta, e, max_team, H=16 * 3600.0):
    """delta may be a scalar or a per-task list (δ_i)."""
    """Load indices determined by the inputs alone.
    w_i(S) = |S|·(D_i + δ·[|S|>1] + e), e = mean empty travel between tasks;
    rho_rigid / rho_flex = Σ_i min_{S ∈ T_i} w_i(S) / (number of vehicles × H);
    rhoB = max_c Σ_{i: under Rigid only single vehicles of capacity ≥ c can carry i} (D_i + e)
           / (number of vehicles of capacity ≥ c × H), the bottleneck load under Rigid;
    rho_star / rho_star_rigid = balanced load index (see rho_star; equal to rho_flex / rho_rigid on a homogeneous
    fleet and at least as large on a mixed fleet).
    Returns None when some task has no admissible team (structurally infeasible)."""
    K = len(caps)
    tot = {}
    for mode in ('rigid', 'flex'):
        s = 0.0
        for q, (m, d) in enumerate(zip(masses, D)):
            ts = minimal_teams(caps, m, mode, max_team)
            if not ts:
                return None
            dq = delta[q] if isinstance(delta, (list, tuple)) else delta
            s += min(len(S) * (d + (dq if len(S) > 1 else 0) + e) for S in ts)
        tot[mode] = s / (K * H)
    rhoB, cB = 0.0, None
    for c in sorted(set(caps)):
        Kc = sum(1 for q in caps if q >= c)
        w = 0.0
        for m, d in zip(masses, D):
            ts = minimal_teams(caps, m, 'rigid', max_team)
            if len(ts[0]) == 1 and min(caps[S[0]] for S in ts) >= c:
                w += d + e
        if w / (Kc * H) > rhoB:
            rhoB, cB = w / (Kc * H), c
    out = dict(rho_rigid=tot['rigid'], rho_flex=tot['flex'], rhoB=rhoB, rhoB_cap=cB)
    for mode in ('flex', 'rigid'):
        out['rho_star' if mode == 'flex' else 'rho_star_rigid'] = (
            tot[mode] if len(set(caps)) == 1 else rho_star(caps, masses, D, delta, e, max_team, H, mode))
    return out


def team_types(caps, m, mode, max_team):
    """Enumerate the team types of minimal_teams by vehicle class (capacity): returns a list of capacity
    multisets (ascending tuples). Follows the rules of minimal_teams one by one (single vehicle Q ≥ m;
    multi-vehicle teams use only vehicles with Q < m, ΣQ ≥ m and removing the smallest member makes the team
    insufficient; rigid gives multi-vehicle teams only when no vehicle of the fleet can carry the block), subject
    to the number of vehicles in each class."""
    cnt = {}
    for q in caps:
        cnt[q] = cnt.get(q, 0) + 1
    singles = [(q,) for q in sorted(cnt) if q >= m]
    if mode == 'single' or (mode == 'rigid' and max(caps) >= m):
        return singles
    light = sorted(q for q in cnt if q < m)
    multi = []
    for size in range(2, max_team + 1):
        for c in itertools.combinations_with_replacement(light, size):
            if any(c.count(q) > cnt[q] for q in set(c)):
                continue
            s = sum(c)
            if s >= m and s - min(c) < m:
                multi.append(c)
    if mode in ('multi', 'rigid'):
        return multi
    if mode == 'flex':
        return singles + multi
    raise ValueError(mode)


def rho_star(caps, masses, D, delta, e, max_team, H=16 * 3600.0, mode='flex'):
    """Balanced load index ρ*: each task may be split fractionally among the team types of this mode, and each
    member vehicle is occupied for D_i + δ_i·[|S|>1] + e; finds the split that minimises the largest class
    utilisation (occupation ÷ (vehicles in the class × H)) by a linear program (GLOP).
    On a homogeneous fleet it equals rho_flex / rho_rigid (for each task the team with the fewest vehicle-hours is
    optimal). Returns None when structurally infeasible."""
    from ortools.linear_solver import pywraplp
    cnt = {}
    for q in caps:
        cnt[q] = cnt.get(q, 0) + 1
    solver = pywraplp.Solver.CreateSolver('GLOP')
    r = solver.NumVar(0.0, solver.infinity(), 'r')
    load = {q: [] for q in cnt}
    for i, (m, d) in enumerate(zip(masses, D)):
        types = team_types(caps, m, mode, max_team)
        if not types:
            return None
        dq = delta[i] if isinstance(delta, (list, tuple)) else delta
        xs = []
        for j, t in enumerate(types):
            x = solver.NumVar(0.0, 1.0, 'x_%d_%d' % (i, j))
            xs.append(x)
            per = (d + (dq if len(t) > 1 else 0) + e) / H
            for q in set(t):
                load[q].append((t.count(q) * per, x))
        solver.Add(solver.Sum(xs) == 1)
    for q, terms in load.items():
        solver.Add(solver.Sum([a * x for a, x in terms]) <= r * cnt[q])
    solver.Minimize(r)
    if solver.Solve() != pywraplp.Solver.OPTIMAL:
        raise RuntimeError('rho_star: the linear program was not solved to optimality')
    return r.solution_value()


def scenario_inst(inst, loads, unloads):
    """Execution evaluation for the handling-variability replay: replace the loading and unloading durations by
    scenario values (lists indexed by task), keep everything else, and return a new Inst.
    Usage: evaluate(scenario_inst(inst, L, U), order, team, lam) -- keeps each vehicle's task order and the teams
    and executes at the earliest start, a team starting only when all members are present; the global order is a
    topological order of the per-vehicle sequences, so it remains valid for any durations."""
    import copy
    d = copy.deepcopy(inst.raw)
    for t, l, u in zip(d['tasks'], loads, unloads):
        t['load'], t['unload'] = int(round(l)), int(round(u))
    return Inst(d)


def order_from_sequences(n, seqs):
    """Per-vehicle sequences -> one global order (a topological order); returns None if there is a circular wait."""
    succ = [set() for _ in range(n)]
    indeg = [0] * n
    for q in seqs:
        for a, b in zip(q, q[1:]):
            if b not in succ[a]:
                succ[a].add(b)
                indeg[b] += 1
    ready = sorted(i for i in range(n) if indeg[i] == 0)
    out = []
    while ready:
        i = ready.pop(0)
        out.append(i)
        for j in sorted(succ[i]):
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
    return out if len(out) == n else None


def summary_hours(ev, inst, lam):
    """Convert an evaluation result to hours for reporting."""
    h = 3600.0
    return dict(obj_h=ev['obj'] / h, tard_h=ev['tard'] / h, crew_h=ev['crew_s'] / h,
                work_h=ev['work'] / h, empty_h=ev['empty'] / h, sync_h=ev['sync'] / h,
                service_h=ev['service'] / h, n_coop=ev['n_coop'], lam=lam)
