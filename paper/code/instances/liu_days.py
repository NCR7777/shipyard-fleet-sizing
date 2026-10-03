"""Second case: scaled workloads and the additions test.

Scaling: k ∈ {1, 2, 4, 6, 8}, seeds 101–105 for each k; k × 50 tasks are drawn with replacement from the 50 tasks of
      Liu 2022 S1 Data, each keeping its day, start time, latest time, origin, destination and mass (so the start
      times within a day follow the original distribution).
Daily decomposition: one instance per day (about 10·k tasks), with time measured from 8:00 of that day (working-
      minute axis); a task spanning the night stays on its start day with its delivery time unchanged (it may exceed
      the 600 min of the day); each vehicle starts every day at the origin of its first task (as in the base setting
      of the second case). Service is aggregated over the week: on-time rate = on-time blocks of the week ÷ blocks of
      the week; mean tardiness per block = tardiness of the week ÷ blocks of the week.
Additions (main test, matching Liu's advice to buy more transporters): the published fleet 250/270/320/380/420 t plus
      n transporters of type X, X ∈ {250, 270, 380, 420} t, n = 0…6, each with flexible coupling (flex) and without
      coupling (rigid; the largest vehicle, 420 t, can carry the heaviest block, 399 t, so rigid means no coupling);
      for each (k, X, model), n*(threshold) = the smallest n from which every larger n meets the threshold (the same
      monotonicity guard as in the earlier ten-instance scan); thresholds as there: on-time rate {90%, 95%}, mean
      tardiness per block {5, 2} min. With n = 0 all X coincide, so it is run once.
Costs (at n*): added transporters, added tonnage, capital proxy Σ c^α (α = 0.6/0.8/1.0), shift staffing
      n × 4 × 10 h/day, and labour hours.
Check: for k = 1, the daily solution and the weekly solution (the whole-week instance of `liu_data.make_case`) should give
      the same weekly utilisation.
End-of-day overrun: the daily decomposition lets work continue after 600 min, which amounts to free overtime.
      Each day instance records the overrun vehicle time (sum over vehicles of the completion after 600 min) and the
      number of vehicles with overrun; at n*, if on some day the overrun vehicle time exceeds 5% of the available
      vehicle time of that day (vehicles × 600 min), the result is flagged as met only with overtime.
Depot sensitivity (same instances): by default each vehicle starts every day at the origin of its first task; the
      sensitivity case uses each of the 8 sites as a fixed depot (start_site argument).
Solver: the configuration in config.json, λ = 0, one run per day instance.
Usage:
  python liu_days.py plan        load of the published fleet for each k
  python liu_days.py run [--procs 20]
  python liu_days.py summary
  python liu_days.py scratch [--procs 20]   second-yard check: the transporter types of the main case (9 homogeneous
                                 tiers and the mixes `MX1`, `MX2`), each sized from scratch (k ∈ {6, 8}; homogeneous
                                 tiers with Flex, mixes with Flex and Rigid; scan rule and K* as in the main case)
  python liu_days.py compare     cheapest type compared with the main case (Liu masses, short handling, baseline dues)
  python liu_days.py parking     depot sensitivity: original 50 tasks and fleet, base setting and each of the 8 sites
                                 as a fixed depot; reports the range of weekly utilisation (whether the 12.15% of the
                                 paper lies in it; the depot is not tuned to reproduce 12.15%)
"""
import json
import multiprocessing as mp
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
sys.path.insert(0, os.path.join(HERE, '..', 'search'))
import params as P                                        # noqa: E402
from core import load_index                               # noqa: E402
from liu_data import make_case, FLEET_LIU2022, DAY_MIN            # noqa: E402
from instance_setup import k_star, THETA, LATE_MIN, CONFIG_FILE   # noqa: E402

PAPER = os.path.normpath(os.path.join(HERE, '..', '..'))
OUT = os.path.join(PAPER, 'runs', 'second_case_scan')
KS = (1, 2, 4, 6, 8)
SEEDS = (101, 102, 103, 104, 105)
ADD_TIERS = (250, 270, 380, 420)
N_ADD = range(0, 7)
MODELS = ('flex', 'rigid')


def base_week():
    return make_case()


def sample_week(k, seed):
    """Draws k × 50 tasks with replacement (keeping all attributes); returns the task list and the base week."""
    W = base_week()
    rng = random.Random(seed * 100 + k)
    return [dict(W['tasks'][rng.randrange(len(W['tasks']))]) for _ in range(k * len(W['tasks']))], W


def day_instance(tasks, W, day, caps, start_site=None):
    """Builds the instance of one day: time shifted so that 8:00 of that day is 0; travel times recomputed from the
    original distance matrix."""
    from liu_data import DIST, V_EMPTY, V_LOADED
    T = [dict(t) for t in tasks if t['batch'] == day]
    off = day * DAY_MIN * 60
    for q, t in enumerate(T):
        t['release'] -= off
        t['due'] -= off
        t['id'] = 'D%dT%03d' % (day, q)
    n = len(T)
    tE = [[0 if i == j else int(round(DIST[T[i]['d_idx']][T[j]['o_idx']] / V_EMPTY)) for j in range(n)] for i in range(n)]
    if start_site is None:
        tE0 = [[0] * n for _ in caps]
    else:
        from liu_data import site_index
        s0 = site_index(start_site)
        tE0 = [[int(round(DIST[s0][t['o_idx']] / V_EMPTY)) for t in T] for _ in caps]
    d = dict(name='liu_day%d' % day, seed=None, tasks=T,
             vehicles=[dict(id='V%d' % (k + 1), cap=c, start=start_site or 'first-task origin') for k, c in enumerate(caps)],
             tauE_start=tE0, tauE=tE, meta=dict(W['meta']))
    d['meta']['crew_team'] = None
    return d


def _cfg():
    if not os.path.exists(CONFIG_FILE):
        raise SystemExit('config.json not found: the solver configuration is required')
    c = {k: (tuple(v) if isinstance(v, list) else v)
         for k, v in json.load(open(CONFIG_FILE, encoding='utf-8')).items() if not k.startswith('_')}
    c['time_limit'] = P.FORMAL_TIME_LIMIT_S
    return c


def solve_week(tasks, W, caps, model, seed, cfg=None, start_site=None):
    from core import Inst, evaluate
    from alns import alns
    cfg = cfg or _cfg()
    tot = dict(n=0, on_time=0, tard_s=0, busy_s=0, crew_s=0, n_coop=0, wall_s=0.0,
               overtime_s=0, overtime_veh=0, overtime_max_ratio=0.0)
    for day in sorted({t['batch'] for t in tasks}):
        d = day_instance(tasks, W, day, caps, start_site)
        if not d['tasks']:
            continue
        inst = Inst(d)
        if inst.n == 1:
            order, team = [0], {0: min(inst.teams(0, model), key=lambda S: (len(S), S))}
            wall = 0.0
        else:
            r = alns(inst, 0.0, model, seed=seed, cfg=cfg)
            order, team, wall = r['order'], {int(i): tuple(S) for i, S in r['team'].items()}, r['wall_s']
        ev = evaluate(inst, order, team, 0.0, detail=True)
        tot['n'] += inst.n
        tot['on_time'] += sum(ev['comp'][i] <= inst.due[i] for i in range(inst.n))
        tot['tard_s'] += ev['tard']
        tot['busy_s'] += ev['empty'] + ev['service'] + ev['sync']
        tot['crew_s'] += ev['crew_s']
        tot['n_coop'] += ev['n_coop']
        tot['wall_s'] += wall
        # end-of-day overrun: the part of each vehicle's last completion of the day after 600 min
        end = [0] * inst.K
        for q, i in enumerate(order):
            for k in team[i]:
                end[k] = max(end[k], ev['comp'][i])
        over = [max(0, e - DAY_MIN * 60) for e in end]
        tot['overtime_s'] += sum(over)
        tot['overtime_veh'] += sum(o > 0 for o in over)
        tot['overtime_max_ratio'] = max(tot['overtime_max_ratio'], sum(over) / (inst.K * DAY_MIN * 60))
    return tot


def _job(a):
    k, seed, X, n, model = a
    tasks, W = sample_week(k, seed)
    caps = list(FLEET_LIU2022) + [X] * n
    r = solve_week(tasks, W, caps, model, seed)
    r.update(k=k, seed=seed, X=X, n_add=n, model=model, util=r['busy_s'] / (len(caps) * 5 * DAY_MIN * 60))
    return r


def plan():
    for k in KS:
        rs = []
        for s in SEEDS:
            tasks, W = sample_week(k, s)
            li = load_index(list(FLEET_LIU2022), [t['mass'] for t in tasks], [t['load'] + t['tauL'] + t['unload'] for t in tasks],
                            60 * P.DELTA_MIN, sum(sum(r) for r in W['tauE']) / (50 * 49), P.MAX_TEAM, H=5 * DAY_MIN * 60.0)
            rs.append(li['rho_flex'])
        print('k = %d: load of the published fleet (5 vehicles) ρ_flex = %.3f '
              '(mean over seeds 101–105; per week, no depot)' % (k, st.mean(rs)))


def run(procs):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'runs.jsonl')
    done = set()
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            r = json.loads(line)
            done.add((r['k'], r['seed'], r['X'], r['n_add'], r['model']))
    jobs = []
    for k in KS:
        for s in SEEDS:
            for m in MODELS:
                for X in ADD_TIERS:
                    for n in N_ADD:
                        Xk = 0 if n == 0 else X            # with n = 0 all X coincide: run once (recorded as X = 0)
                        key = (k, s, Xk, n, m)
                        if key not in done and (k, s, Xk, n, m) not in {j for j in jobs}:
                            jobs.append(key)
    jobs = sorted(set(jobs), key=lambda j: (-j[0], j))
    print('%d runs to do' % len(jobs), flush=True)
    with mp.Pool(procs) as pool, open(path, 'a', encoding='utf-8') as f:
        for r in pool.imap_unordered(_job, jobs):
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
            f.flush()


def summary():
    R = [json.loads(l) for l in open(os.path.join(OUT, 'runs.jsonl'), encoding='utf-8')]
    lines = ['# Second case: additions test (Liu 2022 data scaled; daily decomposition; λ = 0; seeds 101–105)', '',
             '| k | Model | Added type X | n*(90%) | n*(95%) | n*(tardiness per block ≤ 5 min) | n*(≤ 2 min) | '
             'Added tonnage n*(95%)·X | Overrun vehicle time at n*(95%) (h/week) | Met only with overtime |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for k in KS:
        for m in MODELS:
            for X in ADD_TIERS:
                on, lt, ot, om = {}, {}, {}, {}
                for n in N_ADD:
                    Xk = 0 if n == 0 else X
                    rs = [r for r in R if r['k'] == k and r['model'] == m and r['X'] == Xk and r['n_add'] == n]
                    if len(rs) < len(SEEDS):
                        continue
                    on[n] = st.mean(r['on_time'] / r['n'] for r in rs)
                    lt[n] = st.mean(r['tard_s'] / r['n'] / 60 for r in rs)
                    ot[n] = st.mean(r['overtime_s'] for r in rs) / 3600
                    om[n] = max(r['overtime_max_ratio'] for r in rs)
                if not on:
                    continue
                ks = [k_star(on, THETA[0]), k_star(on, THETA[1]), k_star(lt, LATE_MIN[0], le=True), k_star(lt, LATE_MIN[1], le=True)]
                n95 = ks[1]
                lines.append('| %d | %s | %d t | %s | %s | %s | %s | %s | %s | %s |' % (
                    k, 'flexible coupling' if m == 'flex' else 'no coupling', X, *ks,
                    '—' if n95 is None else '%d t' % (n95 * X),
                    '—' if n95 is None else '%.1f' % ot[n95],
                    '—' if n95 is None else ('yes' if om[n95] > 0.05 else 'no')))
    txt = '\n'.join(lines) + '\n'
    open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8').write(txt)
    print(txt)


SCRATCH_KS = (6, 8)
SCRATCH_TYPES = tuple(str(c) for c in (200, 250, 270, 300, 325, 380, 425, 500, 550)) + ('MX1', 'MX2')
SCRATCH_MIXED = {'MX1': 1, 'MX2': 2}
SCRATCH_STEPS = 8
HEAVIEST = 399          # heaviest block in Liu 2022 S1 Data (t)


def _scratch_caps(X, K):
    if X in SCRATCH_MIXED:
        h = SCRATCH_MIXED[X]
        return [550] * h + [270] * (K - h)
    return [int(X)] * K


def _scratch_lb(X):
    from core import minimal_teams
    if X in SCRATCH_MIXED:
        return SCRATCH_MIXED[X] + 1
    return max(1, min(len(S) for S in minimal_teams([int(X)] * 3, HEAVIEST, 'flex', P.MAX_TEAM)))


def _scratch_start(k, X):
    """Starting count, as in the earlier ten-instance scan: the smallest count with load index ≤ 1.1 (per week:
    H = 5 days × 600 min; mean over the 5 seeds); for mixes, 550 t vehicles count as 270 t vehicles here."""
    import math
    Kref = 20
    v = []
    for sd in SEEDS:
        tasks, W = sample_week(k, sd)
        caps = [270] * Kref if X in SCRATCH_MIXED else _scratch_caps(X, Kref)
        li = load_index(caps, [t['mass'] for t in tasks], [t['load'] + t['tauL'] + t['unload'] for t in tasks],
                        60 * P.DELTA_MIN, sum(sum(r) for r in W['tauE']) / (50 * 49), P.MAX_TEAM, H=5 * DAY_MIN * 60.0)
        v.append(li['rho_flex'])
    return max(_scratch_lb(X), math.ceil(st.mean(v) * Kref / 1.1 - 1e-9))


def _scratch_series(a):
    k, X, model = a
    path = os.path.join(OUT, 'scratch', 'k%d_%s_%s.jsonl' % (k, X, model))
    done = {}
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            r = json.loads(line)
            done[(r['K'], r['seed'])] = r
    on, lt = {}, {}

    def measure(K):
        rs = []
        for sd in SEEDS:
            if (K, sd) not in done:
                tasks, W = sample_week(k, sd)
                r = solve_week(tasks, W, _scratch_caps(X, K), model, sd)
                r.update(k=k, X=X, K=K, model=model, seed=sd)
                with open(path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
                done[(K, sd)] = r
            rs.append(done[(K, sd)])
        on[K] = st.mean(r['on_time'] / r['n'] for r in rs)
        lt[K] = st.mean(r['tard_s'] / r['n'] / 60 for r in rs)

    def ok_all(K):
        return on[K] >= THETA[1] and lt[K] <= LATE_MIN[1]

    def fail_all(K):
        return on[K] < THETA[0] and lt[K] > LATE_MIN[0]

    lb = _scratch_lb(X)
    K0 = _scratch_start(k, X)
    measure(K0)
    K = K0
    while not fail_all(K) and K - 1 >= lb:          # downwards
        K -= 1
        measure(K)
    top = max(on)
    while not (ok_all(top) and (top - 1) in on and ok_all(top - 1)) and top < K0 + SCRATCH_STEPS:   # upwards
        top += 1
        measure(top)
    return dict(k=k, X=X, model=model, K0=K0, on=on, late=lt,
                K_star={str(t): k_star(on, t) for t in THETA}, K_star_late={str(L): k_star(lt, L, le=True) for L in LATE_MIN})


def scratch(procs):
    os.makedirs(os.path.join(OUT, 'scratch'), exist_ok=True)
    jobs = [(k, X, m) for k in SCRATCH_KS for X in SCRATCH_TYPES for m in (('flex', 'rigid') if X in SCRATCH_MIXED else ('flex',))]
    lines = ['# Second yard: transporter types of the main case sized from scratch '
             '(Waigaoqiao, Liu 2022 data, k ∈ {6, 8}, seeds 101–105, daily solution, λ = 0)', '',
             'Scan rule and K* definition as in the main case (start at ρ ≤ 1.1; down until both loose thresholds '
             'fail; up until the strictest thresholds hold at two consecutive counts, at most K0 + 8).', '',
             '| k | Model | Type | K0 | K*(90%) | K*(95%) | K*(≤ 5 min) | K*(≤ 2 min) | Total tonnage at K*(95%) |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    with mp.Pool(procs) as pool:
        res = pool.map(_scratch_series, jobs)
    json.dump(res, open(os.path.join(OUT, 'scratch.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for r in sorted(res, key=lambda r: (r['k'], r['model'], SCRATCH_TYPES.index(r['X']))):
        k95 = r['K_star']['0.95']
        lines.append('| %d | %s | %s | %d | %s | %s | %s | %s | %s |' % (
            r['k'], 'flexible coupling' if r['model'] == 'flex' else 'no coupling', r['X'], r['K0'],
            r['K_star']['0.9'], k95,
            r['K_star_late']['5.0'], r['K_star_late']['2.0'], '—' if k95 is None else '%d t' % sum(_scratch_caps(r['X'], k95))))
    txt = '\n'.join(lines) + '\n'
    open(os.path.join(OUT, 'scratch.md'), 'w', encoding='utf-8').write(txt)
    print(txt)


# consistency criterion for the second yard
COMPARE_MAIN = 'liu_short_baseline'     # main-case cell: Liu masses (the 50 real masses), short handling, baseline due dates
COMPARE_ALPHA = 0.8
COMPARE_THETA = '0.95'           # the criterion uses K*(on-time rate 95%); other thresholds are only reported
TIER_ORDER = tuple(str(c) for c in (200, 250, 270, 300, 325, 380, 425, 500, 550))


def _costs(X, K, shift_h):
    caps = _scratch_caps(X, K)
    return {'count': K, 'total tonnage': sum(caps), 'capital proxy': sum((c / 270.0) ** COMPARE_ALPHA for c in caps),
            'shift staffing': 4 * shift_h * K}


def _scan_type(series_name):
    """Series name of the earlier ten-instance scan → type: `'liu_short_baseline_T270'` → `'270'`;
    `'liu_short_baseline_MX2'` → `'MX2'`."""
    tail = series_name[len(COMPARE_MAIN) + 1:]
    return tail[1:] if tail.startswith('T') else tail


def compare():
    """Consistency: for each cost (count, total tonnage, capital proxy with α = 0.8 normalised to one 270 t vehicle,
    shift staffing), the cheapest type of the main case (earlier ten-instance scan, cell `liu_short_baseline`, Flex) and that
    of Waigaoqiao (k = 6 and 8 separately, Flex) are consistent if they are equal or adjacent tiers.
    Adjacent tiers: homogeneous tiers are adjacent in the order 200 < 250 < 270 < 300 < 325 < 380 < 425 < 500 < 550; a
    mix is consistent only with itself. With ties for the cheapest, the sets are consistent if they intersect or
    contain an adjacent pair. Only types that reach K*(95%) in both yards are compared.
    Also reports the Kendall τ-b of the cost rankings (over the types reached in both yards). An inconsistency is
    reported as found, together with the travel-time share and the synchronisation-wait share."""
    from scipy.stats import kendalltau
    scan = {}
    for line in open(os.path.join(PAPER, 'runs', 'earlier_scan', 'summary.jsonl'), encoding='utf-8'):
        s = json.loads(line)
        if s['series'].startswith(COMPARE_MAIN + '_') and isinstance(s['modes'].get('flex'), dict):
            scan[_scan_type(s['series'])] = s['modes']['flex']['K_star'][COMPARE_THETA]
    sc = {(r['k'], r['X']): r['K_star'][COMPARE_THETA] for r in json.load(open(os.path.join(OUT, 'scratch.json'), encoding='utf-8'))
          if r['model'] == 'flex'}

    def adjacent(a, b):
        return a == b or (a in TIER_ORDER and b in TIER_ORDER and abs(TIER_ORDER.index(a) - TIER_ORDER.index(b)) == 1)

    lines = ['# Second yard: consistency of the cheapest type', '',
             '| Waigaoqiao k | Cost | Cheapest, main case | Cheapest, Waigaoqiao | Consistent | Kendall τ-b (types) |',
             '| --- | --- | --- | --- | --- | --- |']
    for k in SCRATCH_KS:
        types = [X for X in SCRATCH_TYPES if scan.get(X) is not None and sc.get((k, X)) is not None]
        for cost in ('count', 'total tonnage', 'capital proxy', 'shift staffing'):
            if len(types) < 2:
                lines.append('| %d | %s | — | — | too few types | — |' % (k, cost))
                continue
            a = {X: _costs(X, scan[X], 16)[cost] for X in types}
            b = {X: _costs(X, sc[(k, X)], 10)[cost] for X in types}
            ma, mb = min(a.values()), min(b.values())
            A_ = [X for X in types if abs(a[X] - ma) < 1e-9]
            B_ = [X for X in types if abs(b[X] - mb) < 1e-9]
            ok = any(adjacent(x, y) for x in A_ for y in B_)
            tau = kendalltau([a[X] for X in types], [b[X] for X in types]).statistic
            lines.append('| %d | %s | %s | %s | %s | %.2f (%d) |' % (k, cost, ', '.join(A_), ', '.join(B_),
                                                                   'yes' if ok else '**no**', tau, len(types)))
    txt = '\n'.join(lines) + '\n'
    open(os.path.join(OUT, 'compare.md'), 'w', encoding='utf-8').write(txt)
    print(txt)


def parking():
    from liu_data import SITES
    W = base_week()
    lines = ['# Second case: depot sensitivity (original 50 tasks, published fleet of 5, without and with flexible '
             'coupling, daily solution, λ = 0, seed 1)', '',
             '| Depot | Model | Weekly utilisation | Tardiness (min) | Overrun vehicle time (h) |',
             '| --- | --- | --- | --- | --- |']
    utils = []
    for site in [None] + list(SITES):
        for m in MODELS:
            r = solve_week(W['tasks'], W, list(FLEET_LIU2022), m, 1, start_site=site)
            u = r['busy_s'] / (len(FLEET_LIU2022) * 5 * DAY_MIN * 60)
            utils.append(u)
            lines.append('| %s | %s | %.2f%% | %.1f | %.2f |' % (site or 'origin of the first task (base setting)', m,
                                                             100 * u, r['tard_s'] / 60, r['overtime_s'] / 3600))
    lines += ['', 'Weekly utilisation range: %.2f%% – %.2f%%; the 12.15%% of the paper %s this range.' % (
        100 * min(utils), 100 * max(utils), 'lies in' if min(utils) <= 0.1215 <= max(utils) else 'lies outside')]
    os.makedirs(OUT, exist_ok=True)
    txt = '\n'.join(lines) + '\n'
    open(os.path.join(OUT, 'parking.md'), 'w', encoding='utf-8').write(txt)
    print(txt)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'plan'
    if cmd == 'plan':
        plan()
    elif cmd == 'run':
        run(int(sys.argv[sys.argv.index('--procs') + 1]) if '--procs' in sys.argv else 20)
    elif cmd == 'summary':
        summary()
    elif cmd == 'parking':
        parking()
    elif cmd == 'scratch':
        scratch(int(sys.argv[sys.argv.index('--procs') + 1]) if '--procs' in sys.argv else 20)
    elif cmd == 'compare':
        compare()
