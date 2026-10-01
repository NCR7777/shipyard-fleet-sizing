"""Driver of the exact comparison on single-batch instances (directory `exact`).

  python exact_run.py pilot <tag> <budget_det> <procs> [n_max]   # trial seeds 9701-9703 as a mini-study (exact/pilot/<tag>/)
  python exact_run.py pilot-report <tag>
  python exact_run.py exact <procs>                              # study seeds, tau from exact/params.json (exact/exact/)
  python exact_run.py greedy                                     # greedy_level G-Flex -> results/exact_greedy.json

Exact scan of a series (floor and ceiling as the ALNS arm): K = floor, floor + 1, ... At each K the route
bounds of all instances are computed first; if they alone exceed the allowance, K fails without a CP-SAT solve.
Otherwise the instances are solved in seed order (budget tau each) and K fails as soon as an instance has no
capped schedule or the proven late bounds exceed the allowance. K passes when every instance has a
replay-checked schedule and the late total is within the allowance. The scan stops at the first passing K;
all instances at K - 1 are then solved in full (K* and K* - 1 complete).
"""
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
EXACT_DIR = STUDY_ROOT / 'exact'
sys.path.insert(0, str(HERE))


def allowance(sp):
    return sp['n_total'] - math.ceil(0.95 * sp['n_total'] - 1e-9)


def verdict(recs, seeds, allowed):
    """recs: seed -> record at one K. 'pass' / 'fail' / 'open'."""
    if any(r['status'] == 'INFEASIBLE' for r in recs.values()):
        return 'fail'
    if sum(r['late_lb'] or 0 for r in recs.values()) > allowed:
        return 'fail'
    if all(s in recs and recs[s]['late'] is not None and recs[s]['replay']['ok'] for s in seeds) and \
            sum(recs[s]['late'] for s in seeds) <= allowed:
        return 'pass'
    return 'open'


def _low():
    import psutil
    p = psutil.Process()
    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    p.cpu_affinity(list(range(1, psutil.cpu_count())))


def exact_series(sp, tau, outdir, low=True):
    if low:
        _low()
    import exact_model as X
    out = outdir / ('%s.jsonl' % sp['name'])
    out.parent.mkdir(parents=True, exist_ok=True)
    recs = {}
    if out.exists():
        for r in map(json.loads, out.read_text(encoding='utf8').splitlines()):
            recs[r['K'], r['seed']] = r                        # a later full solve supersedes a route-only record
    seeds, allowed = sp['seeds'], allowance(sp)
    slices = {}
    for s in seeds:
        d = json.loads((EXACT_DIR / sp['base'][str(s)]).read_text(encoding='utf8'))
        slices[s] = X._sub(d, list(range(min(sp['n_max'], len(d['tasks']))))) if sp.get('n_max') else d

    def put(r):
        with open(out, 'a', encoding='utf8') as f:
            f.write(json.dumps(r) + '\n')
        recs[r['K'], r['seed']] = r
        return r

    def solve(K, s):
        if (K, s) not in recs or recs[K, s]['status'] == 'ROUTE_ONLY':
            r = X.solve_checked(slices[s], sp['family'], K, tau)
            assert r.get('replay', {'ok': True})['ok'], ('replay failed', sp['name'], K, s)
            put(dict(r, series=sp['name'], cell=sp['cell'], family=sp['family'], K=K, seed=s))
        return recs[K, s]

    def route_only(K):
        rows = {}
        for s in seeds:
            if (K, s) in recs:
                rows[s] = recs[K, s]
                continue
            e = X.fleet(slices[s], X.caps_of(sp['family'], K))
            c = X.Capped(e, build=False)                       # structural / window screen only
            if c.trivial:
                rows[s] = dict(status='INFEASIBLE', late=None, late_lb=None, proven=True)
            elif X.triangle_ok(e):
                rows[s] = dict(status='ROUTE_ONLY', late=None, late_lb=len(e['tasks']) - X.route_bound(e), proven=False)
            else:
                rows[s] = dict(status='ROUTE_ONLY', late=None, late_lb=0, proven=False)
        return rows

    def at(K, early):
        if early:
            ro = route_only(K)
            if verdict(ro, seeds, allowed) == 'fail':
                for s, r in ro.items():
                    if (K, s) not in recs:
                        put(dict(series=sp['name'], cell=sp['cell'], family=sp['family'], K=K, seed=s, n=len(slices[s]['tasks']),
                                 det_time=0.0, wall_s=0.0, cpu_s=0.0, route_lb=r['late_lb'], **r))
                return 'fail'
        got = {}
        for s in seeds:
            got[s] = solve(K, s)
            if early and verdict(got, seeds, allowed) == 'fail':
                break
        return verdict(got, seeds, allowed)

    k_pass = None
    for K in range(sp['K_min'], sp['hi_limit'] + 1):
        if at(K, early=True) == 'pass':
            k_pass = K
            break
    if k_pass is not None and k_pass - 1 >= sp['K_min']:
        at(k_pass - 1, early=False)
    return sp['name'], k_pass


def run_series(specs, tau, outdir, procs):
    with ProcessPoolExecutor(procs) as ex:
        futs = [ex.submit(exact_series, sp, tau, outdir) for sp in sorted(specs, key=lambda sp: sp['name'])]
        for f in as_completed(futs):
            print(*f.result(), flush=True)


# ---------------------------------------------------------------- pilot (trial seeds only)
def pilot_specs(n_max=None):
    import exact_slices as V
    index = json.loads((EXACT_DIR / 'slices_trial.json').read_text(encoding='utf8'))
    specs = []
    for cell in V.CELLS:
        rows = [r for r in index if r['cell'] == cell]
        ds = {r['seed']: json.loads((EXACT_DIR / r['file']).read_text(encoding='utf8')) for r in rows}
        if n_max:
            ds = {s: dict(d, tasks=d['tasks'][:n_max]) for s, d in ds.items()}   # task list only; floor and n_total
        for fam in V.families(cell):
            k0 = max(V.k_lb(d, fam) for d in ds.values())
            specs.append(dict(name='P_%s_%s' % (cell, fam), cell=cell, family=fam, K_min=k0, hi_limit=k0 + 8,
                              seeds=V.SEEDS['trial'], base={str(r['seed']): r['file'] for r in rows}, n_max=n_max,
                              n_total=sum(len(d['tasks']) for d in ds.values())))
    return specs


def pilot(tag, budget, procs, n_max=None):
    outdir = EXACT_DIR / 'pilot' / tag
    outdir.mkdir(parents=True, exist_ok=True)
    specs = pilot_specs(n_max)
    (outdir / 'series.json').write_text(json.dumps(specs, indent=1) + '\n', encoding='utf8')
    run_series(specs, budget, outdir, procs)


def _ext_records(tag):
    """Extension re-solves of a pilot: the record with the largest budget per solve."""
    p = EXACT_DIR / 'pilot' / (tag + '_ext') / 'records.jsonl'
    out = {}
    if p.exists():
        for r in map(json.loads, p.read_text(encoding='utf8').splitlines()):
            key = (r['series'], r['K'], r['seed'])
            if key not in out or r['det_budget'] > out[key]['det_budget']:
                out[key] = r
    return out


def _extend_one(job):
    _low()
    import exact_model as X
    sp, K, s, budget = job
    d = json.loads((EXACT_DIR / sp['base'][str(s)]).read_text(encoding='utf8'))
    if sp.get('n_max'):
        d = X._sub(d, list(range(min(sp['n_max'], len(d['tasks'])))))
    r = X.solve_checked(d, sp['family'], K, budget)
    assert r.get('replay', {'ok': True})['ok'], ('replay failed', sp['name'], K, s)
    r.pop('start', None), r.pop('team', None)
    return dict(r, series=sp['name'], cell=sp['cell'], family=sp['family'], K=K, seed=s)


def pilot_extend(tag, budget, procs, stop=False):
    """Re-solve the still unproven boundary solves with a larger budget. With stop, end as soon as the 95% rule is
    decided: proven >= ceil(0.95 n) (met) or unproven > n - ceil(0.95 n) among solves done at this budget (not met)."""
    import psutil
    specs = {sp['name']: sp for sp in json.loads((EXACT_DIR / 'pilot' / tag / 'series.json').read_text(encoding='utf8'))}
    bnd = pilot_report(tag, quiet=True)['_boundary']
    need = math.ceil(0.95 * len(bnd))
    todo = [(specs[r['series']], r['K'], r['seed'], budget) for r in bnd if not r['proven'] and r['det_budget'] < budget]
    proven = sum(r['proven'] for r in bnd)
    fails = 0
    out = EXACT_DIR / 'pilot' / (tag + '_ext') / 'records.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    print('extending %d solves to %g (proven %d of %d, need %d)' % (len(todo), budget, proven, len(bnd), need), flush=True)
    ex = ProcessPoolExecutor(procs)
    futs = [ex.submit(_extend_one, j) for j in todo]
    decided = None
    for f in as_completed(futs):
        r = f.result()
        with open(out, 'a', encoding='utf8') as fh:
            fh.write(json.dumps(r) + '\n')
        proven += r['proven']
        fails += not r['proven']
        print(r['series'], r['K'], r['seed'], r['status'], r['late'], r['late_lb'], round(r['det_time'], 1), flush=True)
        if stop and (proven >= need or fails > len(bnd) - need):
            decided = 'met' if proven >= need else 'not met'
            break
    if decided:
        for f in futs:
            f.cancel()
        for c in psutil.Process().children(recursive=True):
            c.kill()
        ex.shutdown(wait=False, cancel_futures=True)
    else:
        ex.shutdown()
    print('rule 1 at budget %g: %s' % (budget, decided or 'all done'), flush=True)


def pilot_report(tag, quiet=False):
    outdir = EXACT_DIR / 'pilot' / tag
    specs = json.loads((outdir / 'series.json').read_text(encoding='utf8'))
    ext = _ext_records(tag)
    rows, bnd, summary = [], [], []
    for sp in specs:
        p = outdir / ('%s.jsonl' % sp['name'])
        if not p.exists():
            continue
        recs = {}
        for r in map(json.loads, p.read_text(encoding='utf8').splitlines()):
            recs[r['K'], r['seed']] = r
        rows += [r for r in recs.values() if r['status'] != 'ROUTE_ONLY']
        ks = sorted({K for K, _ in recs})
        v = {K: verdict({s: recs[K, s] for s in sp['seeds'] if (K, s) in recs}, sp['seeds'], allowance(sp)) for K in ks}
        kp = next((K for K in ks if v[K] == 'pass'), None)
        if kp is not None:
            bnd += [recs[K, s] for K in (kp - 1, kp) for s in sp['seeds'] if (K, s) in recs and recs[K, s]['status'] != 'ROUTE_ONLY']
        summary.append((sp['name'], sp['K_min'], kp, ''.join(v[K][0] for K in ks)))
    bnd = [ext.get((r['series'], r['K'], r['seed']), r) if not r['proven'] else r for r in bnd]    # extension re-solves
    proven = lambda r: r['proven']
    dts = sorted(r['det_time'] if proven(r) else math.inf for r in bnd)
    need = math.ceil(0.95 * len(dts)) if dts else 0
    cpu = sum(r['cpu_s'] for r in rows)
    s = dict(tag=tag, series=len(summary), series_passed=sum(k is not None for _, _, k, _ in summary),
             full_solves=len(rows), boundary_solves=len(bnd), boundary_proven=sum(map(proven, bnd)),
             tau95_det=dts[need - 1] if dts else None, det_per_cpu_s=sum(r['det_time'] for r in rows) / max(cpu, 1e-9),
             cpu_core_h=cpu / 3600, wall_h=sum(r['wall_s'] for r in rows) / 3600,
             replay_failures=sum(1 for r in rows if r.get('replay') and not r['replay']['ok']))
    s['study_core_h_estimate'] = s['cpu_core_h'] * 10 / 3
    s['extension_records'] = len(ext)
    if not quiet:
        print(json.dumps(s, indent=1))
        for x in summary:
            print(*x)
    s['_boundary'] = bnd
    return s


# ---------------------------------------------------------------- study
def exact(procs):
    tau = json.loads((EXACT_DIR / 'params.json').read_text(encoding='utf8'))['tau_det']
    run_series(json.loads((EXACT_DIR / 'series.json').read_text(encoding='utf8')), tau, EXACT_DIR / 'exact', procs)


def greedy():
    """greedy_level.scan on the series of this study: K from the floor to floor + 8 (K_start passed as hi_limit - 10
    because greedy_level scans to K_start + 10), same seeds and allowance as the other arms."""
    import greedy_level as G
    res = {}
    for sp in json.loads((EXACT_DIR / 'series.json').read_text(encoding='utf8')):
        G.SEEDS, G.NEED = sp['seeds'], math.ceil(0.95 * sp['n_total'] - 1e-9)
        name, r = G.scan((EXACT_DIR, dict(sp, K_start=sp['hi_limit'] - 10)))
        assert max(r['runs']) <= sp['hi_limit']
        res[name] = r
    (STUDY_ROOT / 'results' / 'exact_greedy.json').write_text(json.dumps(res) + '\n', encoding='utf8')
    print(json.dumps({k: v['K_greedy'] for k, v in res.items()}))


def selfcheck():
    """Verdict rule on synthetic records (allowance 2)."""
    ok = lambda late, lb: dict(status='OPTIMAL' if late == lb else 'FEASIBLE', late=late, late_lb=lb, replay=dict(ok=True))
    seeds = [1, 2, 3]
    assert verdict({1: ok(1, 1), 2: ok(1, 0), 3: ok(0, 0)}, seeds, 2) == 'pass'
    assert verdict({1: ok(1, 1), 2: ok(2, 2)}, seeds, 2) == 'fail'                       # early: bounds exceed
    assert verdict({1: dict(status='INFEASIBLE', late=None, late_lb=None)}, seeds, 2) == 'fail'
    assert verdict({1: dict(status='ROUTE_ONLY', late=None, late_lb=2), 2: dict(status='ROUTE_ONLY', late=None, late_lb=1)}, seeds, 2) == 'fail'
    assert verdict({1: ok(2, 1), 2: ok(1, 0), 3: ok(0, 0)}, seeds, 2) == 'open'
    assert verdict({1: ok(0, 0), 2: ok(0, 0)}, seeds, 2) == 'open'                       # not all solved
    # end to end: one real pilot series with a small budget into a temporary directory
    import tempfile
    sp = next(x for x in pilot_specs() if x['name'] == 'P_liu_short_baseline_L300_H425x1')
    with tempfile.TemporaryDirectory() as tmp:
        name, kp = exact_series(dict(sp, hi_limit=sp['K_min'] + 3), 5.0, Path(tmp), low=False)
        recs = [json.loads(l) for l in (Path(tmp) / (name + '.jsonl')).read_text(encoding='utf8').splitlines()]
    full = [r for r in recs if r['status'] != 'ROUTE_ONLY']
    assert full and all(r['replay']['ok'] for r in full if r['late'] is not None), recs
    if kp is not None:
        assert all(any(r['K'] == K and r['seed'] == s for r in full) for K in (kp - 1, kp) if K >= sp['K_min'] for s in sp['seeds'])
    print('exact_run self-check passed (end to end: %s, K_pass %s, %d records, %d full solves)' % (name, kp, len(recs), len(full)))


if __name__ == '__main__':
    a = sys.argv[1:]
    {'pilot': lambda: pilot(a[1], float(a[2]), int(a[3]), int(a[4]) if len(a) > 4 else None),
     'pilot-report': lambda: pilot_report(a[1]),
     'pilot-extend': lambda: pilot_extend(a[1], float(a[2]), int(a[3]), stop=len(a) > 4 and a[4] == 'stop'),
     'exact': lambda: exact(int(a[1])), 'greedy': greedy, 'selfcheck': selfcheck}[a[0]]()
