"""Fleet-count scan (earlier ten-instance scan): for each transporter type in each cell, finds the smallest count K*
that meets a service threshold; costs are compared afterwards.

Types: 9 homogeneous tiers (200, 250, 270, 300, 325, 380, 425, 500, 550 t); 2 mixes (1 × 550 or 2 × 550 plus
n × 270; only the number of 270 t vehicles is scanned).
Cells: 6 mass scenarios × 3 handling settings × 2 due-date levels (baseline empirical distribution, tight
U(120,150)); structurally infeasible type × mass combinations are excluded beforehand.
Instances: 97 tasks, 16 h, 8 batches; seeds 101–110 (seeds 1–2 were a small pilot and are not in the results).
Solver: configuration config.json, ALNS-Flex (mixes also Rigid), λ = 0 (lexicographic: tardiness first, then
      labour counted per vehicle, P-veh), one run per instance, time_limit = 1800 s (a safeguard only; max_iter
      decides).
On-time rate: share of blocks delivered on time (completion ≤ delivery time), mean over the 10 instances.
Thresholds θ ∈ {90%, 95%}.
Service measures: K* is found for both
  on-time rate θ ∈ {90%, 95%} and mean tardiness per block L ∈ {5 min, 2 min} (total tardiness ÷ tasks of each of
  the 10 instances, averaged).
Count scan:
  1. start K0 = the smallest count with ρ_flex ≤ 1.1 (ρ_flex averaged over the 10 instances, core.load_index);
     for mixes, 550 t vehicles count as 270 t vehicles when computing the start (a start that is too high does no
     harm, the downward scan corrects it);
  2. downwards: unless K0 is below both loose thresholds at once (on-time rate < 90% and tardiness per block > 5 min),
     scan K0−1, K0−2, … until a count is below both loose thresholds or the structural lower bound is reached;
  3. upwards: from the highest scanned count, add one vehicle at a time until the two highest consecutive counts
     both meet the two strictest thresholds (on-time rate ≥ 95% and tardiness per block ≤ 2 min), at most K0 + 8;
  4. K*(threshold) = the smallest count from which every larger scanned count meets the threshold (this guards
     against non-monotonicity caused by solver noise); None if not reached.
  5. two-stage variant: the scan uses one run per (count, instance);
     then, for each threshold, K*−1 and K* are rerun up to R runs (run j = 0…R−1, ALNS seed = instance seed + 1000·j)
     keeping the run with the best objective; K* is re-evaluated using the best run at the rerun counts and the first
     run at the other counts; if K* moves, the new boundary is rerun once more, at most two rounds.
     With STAGE2 = (3, 6), the same procedure is repeated up to 6 runs and the interval [K*(R = 3), K*(R = 6)] is
     reported.

Recorded per run: on-time blocks, tardiness, labour hours (the same schedule counted under P-veh and under P-team),
coupled tasks, iterations, time and the solution (reused by the handling-variability replay).
Usage:
  python instance_setup.py plan                 # list all series and starting counts K0 (inputs only, no solving)
  python instance_setup.py run [--procs 20] [--only series-name-prefix ...] [--dry]   # resumable
"""
import json
import math
import multiprocessing as mp
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
sys.path.insert(0, os.path.join(HERE, '..', 'search'))
import params as P      # noqa: E402

PAPER = os.path.normpath(os.path.join(HERE, '..', '..'))
OUT = os.path.join(PAPER, 'runs', 'earlier_scan')
SEEDS = tuple(range(101, 111))
N_TASKS = 97
TIERS = (200, 250, 270, 300, 325, 380, 425, 500, 550)
MIXED = {'MX1': 1, 'MX2': 2}          # 1 × 550 or 2 × 550, plus n × 270
DUES = {'baseline': P.DUE_EMPIRICAL, 'tight': P.DUE_TIGHT}
THETA = (0.90, 0.95)
LATE_MIN = (5.0, 2.0)      # thresholds of mean tardiness per block (min)
RHO_START = 1.1
MAX_STEPS = 8
LAM = 0.0
# None: one run per instance; (3,): two-stage; (3, 6): two-stage with an interval. None, because the K* stability
# check passed with R = 1.
STAGE2 = None
STAGE2_ROUNDS = 2


def caps_of(vtype, K):
    if vtype in MIXED:
        h = MIXED[vtype]
        return [550] * h + [270] * (K - h)
    return [int(vtype)] * K


def min_K(vtype):
    return MIXED[vtype] + 1 if vtype in MIXED else P.MAX_TEAM


def series_list():
    out = []
    for ms in P.MASS_SCEN_SCAN:
        for hs in P.HANDLING:
            for dk in DUES:
                for c in TIERS:
                    if 3 * c < {'jiang': 450, 'lightskew': 500, 'uniform': 500, 'extraheavy': 800, 'rohcha': 544, 'liu': 399}[ms]:
                        continue            # structurally infeasible: no team of 3 can carry the heaviest block
                    out.append(dict(name='%s_%s_%s_T%d' % (ms, hs, dk, c), vtype=str(c), ms=ms, hs=hs, dk=dk, modes=('flex',)))
                for mx in MIXED:
                    out.append(dict(name='%s_%s_%s_%s' % (ms, hs, dk, mx), vtype=mx, ms=ms, hs=hs, dk=dk, modes=('flex', 'rigid')))
    # Scale effect: 270, 300, 550 t × light-skewed and Roh–Cha masses × short handling × baseline due dates, with
    # twice the tasks (194, 16 h, 8 batches); compares K*(2n) with 2K*(n)
    for ms in ('lightskew', 'rohcha'):
        for c in (270, 300, 550):
            out.append(dict(name='double_%s_short_baseline_T%d' % (ms, c), vtype=str(c), ms=ms, hs='short', dk='baseline', modes=('flex',),
                            n_tasks=2 * N_TASKS))
    return out


def make(vtype, K, ms, hs, dk, seed, caps=None, gen=None, n_tasks=None):
    """gen: extra arguments for instgen.make_instance (factors of the one-factor sensitivity study, such as delta_min,
    handling_factor, speed, max_team, turn_tau, delta_turn); not used by the scan itself."""
    import instgen
    n = n_tasks or N_TASKS
    return instgen.make_instance('scan_%s_K%d_%s_%s_%s_n%d_s%d' % (vtype, K, ms, hs, dk, n, seed) if n != N_TASKS
                                 else 'scan_%s_K%d_%s_%s_%s_s%d' % (vtype, K, ms, hs, dk, seed), seed, n,
                                 caps if caps is not None else caps_of(vtype, K), ms, hs, due_min=DUES[dk], jiang_dedup=True,
                                 **(gen or {}))


def rho_flex(vtype, K, ms, hs, dk, gen=None, n_tasks=None):
    v = []
    for s in SEEDS:
        # Mixes: 550 t vehicles count as 270 t vehicles for the start; if that gives no value (e.g. with teams of at
        # most 2, two 270 t vehicles cannot carry the heaviest block), the actual fleet is used; this affects only the
        # start, and feasibility is still judged on the actual fleet
        caps = [270] * K if vtype in MIXED else None
        li = make(vtype, K, ms, hs, dk, s, caps=caps, gen=gen, n_tasks=n_tasks)['meta']['load_index']
        if li is None and caps is not None:
            li = make(vtype, K, ms, hs, dk, s, gen=gen, n_tasks=n_tasks)['meta']['load_index']
        if li is None:
            return None
        v.append(li['rho_flex'])
    return st.mean(v)


def start_K(vtype, ms, hs, dk, gen=None, n_tasks=None):
    """Smallest count with ρ_flex ≤ 1.1. ρ_flex decreases monotonically with the count (for one type the sum of
    minimal team vehicle times does not depend on the count, which enters only the denominator), so the total vehicle
    time is computed at one count and the start is solved from it. Returns (None, None) if structurally infeasible
    (some task has no feasible team)."""
    Kref = 20
    r = rho_flex(vtype, Kref if not n_tasks else 2 * Kref, ms, hs, dk, gen, n_tasks)
    if n_tasks:
        Kref = 2 * Kref
    if r is None:
        return None, None
    W = r * Kref                                   # total minimal team vehicle time in units of (vehicles × H)
    return max(min_K(vtype), math.ceil(W / RHO_START - 1e-9)), W


CONFIG_FILE = os.path.join(HERE, '..', 'search', 'config.json')   # solver configuration; an error if missing


def _cfg():
    if not os.path.exists(CONFIG_FILE):
        raise SystemExit('config.json not found: the solver configuration is required')
    c = json.load(open(CONFIG_FILE, encoding='utf-8'))
    c = {k: (tuple(v) if isinstance(v, list) else v) for k, v in c.items() if not k.startswith('_')}
    c['time_limit'] = P.FORMAL_TIME_LIMIT_S
    return c


def run_one(sr, mode, K, seed, j=0):
    """j: the j-th run on the same (count, instance), ALNS seed = instance seed + 1000·j (j = 0 is the single run)."""
    from core import Inst, evaluate
    from alns import alns
    d = make(sr['vtype'], K, sr['ms'], sr['hs'], sr['dk'], seed, gen=sr.get('gen'), n_tasks=sr.get('n_tasks'))
    inst = Inst(d)
    r = alns(inst, LAM, mode, seed=seed + 1000 * j, cfg=_cfg())
    team = {int(i): tuple(S) for i, S in r['team'].items()}
    ev = evaluate(inst, r['order'], team, LAM, detail=True)
    d2 = json.loads(json.dumps(d))
    d2['meta']['crew_team'] = P.CREW_TEAM_ONE_UNIT
    ev_team = evaluate(Inst(d2), r['order'], team, LAM)
    on_time = sum(ev['comp'][i] <= inst.due[i] for i in range(inst.n))
    return dict(series=sr['name'], vtype=sr['vtype'], mode=mode, K=K, seed=seed, j=j, obj=r['obj'], n=inst.n, on_time=on_time,
                tard_s=ev['tard'], crew_s_veh=ev['crew_s'], crew_s_team=ev_team['crew_s'], work_s=ev['work'],
                empty_s=ev['empty'], sync_s=ev['sync'], n_coop=ev['n_coop'], iters=r['iters'], wall_s=r['wall_s'],
                rho=d['meta']['load_index'], order=r['order'], team={int(i): list(S) for i, S in team.items()})


def k_star(rates, theta, le=False):
    """rates: {K: measure}. The smallest count from which every larger scanned count meets the threshold; None if
    there is none. le=False: measure ≥ threshold meets it (on-time rate); le=True: measure ≤ threshold meets it
    (mean tardiness per block)."""
    Ks = sorted(rates)
    best = None
    for K in reversed(Ks):
        ok = rates[K] <= theta if le else rates[K] >= theta
        if ok:
            best = K
        else:
            break
    return best


def _series_job(args):
    sr, done_path, dry = args
    done = {}
    if os.path.exists(done_path):
        for line in open(done_path, encoding='utf-8'):
            r = json.loads(line)
            done[(r['mode'], r['K'], r['seed'], r.get('j', 0))] = r
    K0, W = start_K(sr['vtype'], sr['ms'], sr['hs'], sr['dk'], sr.get('gen'), sr.get('n_tasks'))
    summary = dict(series=sr['name'], K0=K0, W=W, modes={}, gen=sr.get('gen'))
    if K0 is None:
        summary['modes'] = {m: 'structurally infeasible' for m in sr['modes']}
        return summary
    for mode in sr['modes']:
        rates, late = {}, {}

        def measure(K):
            rs, ls = [], []
            for s in SEEDS:
                key = (mode, K, s, 0)
                if key not in done:
                    if dry:
                        return None
                    r = run_one(sr, mode, K, s)
                    with open(done_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(r, ensure_ascii=False) + '\n')
                    done[key] = r
                rs.append(done[key]['on_time'] / done[key]['n'])
                ls.append(done[key]['tard_s'] / done[key]['n'] / 60.0)
            rates[K], late[K] = st.mean(rs), st.mean(ls)
            return True

        def ok_all(K):
            return rates[K] >= THETA[1] and late[K] <= LATE_MIN[1]

        def fail_all(K):
            return rates[K] < THETA[0] and late[K] > LATE_MIN[0]

        if measure(K0) is None:
            summary['modes'][mode] = 'dry'
            continue
        K = K0
        while not fail_all(K) and K - 1 >= min_K(sr['vtype']):      # downwards
            K -= 1
            measure(K)
        top = max(rates)
        while not (ok_all(top) and (top - 1) in rates and ok_all(top - 1)) and top < K0 + MAX_STEPS:   # upwards
            top += 1
            measure(top)
        summary['modes'][mode] = dict(
            rates={int(k): v for k, v in sorted(rates.items())}, late_min={int(k): v for k, v in sorted(late.items())},
            K_star={str(t): k_star(rates, t) for t in THETA},
            K_star_late={str(L): k_star(late, L, le=True) for L in LATE_MIN})
        if STAGE2:
            summary['modes'][mode]['stage2'] = _stage2(sr, mode, sorted(rates), done, done_path)
    return summary


def _stage2(sr, mode, Ks, done, done_path):
    """Two-stage variant (item 5 of the module docstring). Ks: scanned counts. Reruns and re-evaluates K* for each
    R ∈ STAGE2 and each threshold."""
    def ensure(K, R):
        for s in SEEDS:
            for j in range(R):
                key = (mode, K, s, j)
                if key not in done:
                    r = run_one(sr, mode, K, s, j)
                    with open(done_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(r, ensure_ascii=False) + '\n')
                    done[key] = r

    def metrics(refined, R):
        on, lt = {}, {}
        for K in Ks:
            rs, ls = [], []
            for s in SEEDS:
                nb = R if K in refined else 1
                b = min((done[(mode, K, s, j)] for j in range(nb)), key=lambda r: (r.get('obj', r['tard_s']), r.get('j', 0)))
                rs.append(b['on_time'] / b['n'])
                ls.append(b['tard_s'] / b['n'] / 60.0)
            on[K], lt[K] = st.mean(rs), st.mean(ls)
        return on, lt

    out = {}
    for R in STAGE2:
        res = {}
        for name, thr, le in [('%s' % t, t, False) for t in THETA] + [('late%s' % L, L, True) for L in LATE_MIN]:
            refined = set()
            on, lt = metrics(refined, R)
            ks = k_star(lt if le else on, thr, le=le)
            hist = [ks]
            for _ in range(STAGE2_ROUNDS):
                if ks is None:
                    break
                new = {K for K in (ks - 1, ks) if K in Ks} - refined
                if not new:
                    break
                for K in sorted(new):
                    ensure(K, R)
                refined |= new
                on, lt = metrics(refined, R)
                ks2 = k_star(lt if le else on, thr, le=le)
                hist.append(ks2)
                if ks2 == ks:
                    break
                ks = ks2
            res[name] = dict(K_star=ks, history=hist, refined=sorted(refined))
        out[str(R)] = res
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'plan'
    S = series_list()
    if '--only' in sys.argv:
        i = sys.argv.index('--only') + 1
        pref = []
        while i < len(sys.argv) and not sys.argv[i].startswith('--'):
            pref.append(sys.argv[i]); i += 1
        S = [s for s in S if any(s['name'].startswith(p) for p in pref)]
    if cmd == 'plan':
        for sr in S:
            K0, W = start_K(sr['vtype'], sr['ms'], sr['hs'], sr['dk'], sr.get('gen'), sr.get('n_tasks'))
            print('%-26s K0 = %s  (total minimal team vehicle time = %s vehicles × 16 h)' % (
                sr['name'], 'structurally infeasible' if K0 is None else '%2d' % K0, '—' if W is None else '%.2f' % W))
        print('%d series' % len(S))
        return
    procs = int(sys.argv[sys.argv.index('--procs') + 1]) if '--procs' in sys.argv else 20
    dry = '--dry' in sys.argv
    os.makedirs(os.path.join(OUT, 'series'), exist_ok=True)
    jobs = [(sr, os.path.join(OUT, 'series', sr['name'] + '.jsonl'), dry) for sr in S]
    with mp.Pool(procs) as pool, open(os.path.join(OUT, 'summary.jsonl'), 'a', encoding='utf-8') as f:
        for summ in pool.imap_unordered(_series_job, jobs):
            f.write(json.dumps(summ, ensure_ascii=False) + '\n')
            f.flush()
            print(summ['series'], summ['K0'], {m: (v if isinstance(v, str) else (v['K_star'], v['K_star_late']))
                                               for m, v in summ['modes'].items()}, flush=True)


if __name__ == '__main__':
    main()
