"""Further fleet-count studies on the main specification with the same scheduler as the main study (directory
`main`): one-factor sensitivity (`sensitivity`) with its coupling-time axis (`delta_axis`, `delta_axis_mix`), tier-specific speeds (`tier_speeds`,
`tier_speeds_jiang`), heavy-block share (`heavy_share`), the second case on the published data of Liu et al. (2022) (`second_case`),
overweight-only coupling runs (`overweight_only`) and the exact comparison on single-batch instances (`exact`). fleet_scan.py is
imported unchanged, so the file hashes recorded for the main study stay valid. Starting counts: each experiment's
original K* at 95% (its summary.jsonl); where missing, the reference count of the earlier ten-instance scan + 2.
Runs are started at below-normal process priority so that they use only CPU left idle by the main study.

  python fleet_scan_studies.py prepare-sensitivity sensitivity | prepare-tier-speeds tier_speeds | prepare-heavy-share heavy_share | prepare-second-case second_case
  python fleet_scan_studies.py run <study> [workers]
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet_scan                                             # noqa: E402

ROOT, STUDY_ROOT = fleet_scan.ROOT, fleet_scan.STUDY_ROOT
PAPER = ROOT / 'paper'
LIU_FLEET = [250, 270, 320, 380, 420]
CASE_KS, CASE_WEEKS = (1, 2, 4, 6, 8), tuple(range(101, 107))
_caps0, _kmin0 = fleet_scan.caps_of, fleet_scan.kmin_of


def caps_of(fam, K):
    """'ADD<X>': Liu's published fleet plus K - 5 transporters of X t (second case)."""
    if fam.startswith('ADD'):
        return LIU_FLEET + [int(fam[3:])] * (K - len(LIU_FLEET))
    return _caps0(fam, K)


def kmin_of(fam):
    return len(LIU_FLEET) if fam.startswith('ADD') else _kmin0(fam)


class Series(fleet_scan.Series):
    """Service need from the series' own task total (second case: day instances of varying size)."""
    def __init__(self, spec, study, n_tasks=97):
        super().__init__(spec, study, n_tasks)
        if 'n_total' in spec:
            self.need = math.ceil(0.95 * spec['n_total'] - 1e-9)
        if 'hi_limit' in spec:
            self.hi_limit = spec['hi_limit']          # exact single-batch comparison: structural floor + 8


# fleet_scan.py stays unchanged; its module globals are extended here (parent process only)
fleet_scan.caps_of, fleet_scan.kmin_of, fleet_scan.Series = caps_of, kmin_of, Series


def summary_k(path):
    out = {}
    for line in Path(path).read_text(encoding='utf8').splitlines():
        r = json.loads(line)
        m = r.get('modes', {}).get('flex')
        if isinstance(m, dict):
            out[r['series']] = m['K_star'].get('0.95')
    return out


def earlier_counts():
    return {r['series']: r['modes']['flex']['K_star']['0.95'] for r in
            (json.loads(l) for l in (PAPER / 'runs/earlier_scan/summary.jsonl').read_text(encoding='utf8').splitlines())
            if isinstance(r['modes'].get('flex'), dict)}


def tname(t):
    return t if t.startswith('MX') else 'T' + t


def build(study, items, seeds, offset):
    """items: (name, cell, family, gen, K_start)."""
    fleet_scan._paper_path()
    bases, specs = {}, []
    for name, cell, fam, gen, k0 in items:
        key = (cell, json.dumps(gen, sort_keys=True))
        if key not in bases:
            bases[key] = {str(s): fleet_scan.make_base(study, cell, s, gen) for s in seeds}
        specs.append(dict(name=name, cell=cell, family=fam, K_start=k0, K_min=fleet_scan.kmin_of(fam), objective='cap',
                          tmax_s=7200, seed_offset=offset, gen=gen, base=bases[key], seeds=seeds))
    fleet_scan.write_series(study, specs)


SENS_BOUNDARY = {   # second side of the unmeasured parameters (decision boundaries)
    'delta30': dict(delta_min=30), 'delta40': dict(delta_min=40),
    'hand1.5': dict(handling_factor=1.5), 'hand2.0': dict(handling_factor=2.0),
    'speed0.75': dict(speed='x0.75'),
}


def prepare_sensitivity(study):
    sys.path.insert(0, str(PAPER / 'code' / 'instances'))
    fleet_scan._paper_path()
    import params as P
    P.SPEEDS.setdefault('x0.75', (9.0 / 3.6, 4.5 / 3.6))       # 0.75 x the 12/6 km/h base
    import sensitivity_setup as X
    ks, scan_counts = summary_k(PAPER / 'runs/earlier_sensitivity/summary.jsonl'), earlier_counts()
    items = []
    for fk, gen in dict(X.FACTORS, **SENS_BOUNDARY).items():
        for ms, hs, dk in X.CELLS:
            for t in X.TYPES:
                name = '%s_%s_%s_%s_%s' % (fk, ms, hs, dk, tname(t))
                k0 = ks.get(name) or (scan_counts.get('%s_%s_%s_%s' % (ms, hs, dk, tname(t))) or 10) + 2
                if name in ks and ks[name] is None and gen.get('max_team') == 2:
                    continue                    # structurally infeasible with two-member teams
                items.append((name, '%s_%s_%s' % (ms, hs, dk), t, gen, k0))
    build(study, items, fleet_scan.SEEDS, 60000)


def prepare_tier_speeds(study):
    sys.path.insert(0, str(PAPER / 'tier_speed_setup'))
    import tier_speed_setup as X
    import tier_speed_liu as Y
    X.init()
    ks = summary_k(PAPER / 'runs/earlier_tier_speeds/summary.jsonl')
    scan_counts = earlier_counts()
    items = []
    for cells, new in ((X.CELLS, X.NEW), (Y.CELLS6, Y.NEW6)):
        for ms, hs, dk in cells:
            for t, key in new.items():
                name = 'tierspeed_%s_%s_%s_%s' % (ms, hs, dk, tname(t))
                k0 = ks.get(name) or (scan_counts.get('%s_%s_%s_%s' % (ms, hs, dk, tname(t))) or 10) + 1
                items.append((name, '%s_%s_%s' % (ms, hs, dk), t, {'speed': key}, k0))
    # expanded Liu mixes and `MX1` in `liu_short_baseline`, every member at 10/5 km/h (`tier380`);
    # start = known count under the 120-min cap (start counts of the delay-cap study, 120-min level) + 1,
    # as in the tier-speed rule above
    cap_counts = json.loads((STUDY_ROOT / 'results' / 'delay_cap_start_counts.json').read_text(encoding='utf8'))
    cell = 'liu_short_baseline'
    for fam in ['L300_H425x%d' % h for h in (1, 2, 3, 4)] + ['L270_H425x%d' % h for h in (1, 2, 3, 4)] + ['MX1']:
        k_ref = cap_counts.get('120|%s|%s' % (cell, fam)) or scan_counts.get('%s_%s' % (cell, tname(fam)))
        items.append(('tierspeed_%s_%s' % (cell, fam), cell, fam, {'speed': 'tier380'}, (k_ref or 10) + 1))
    build(study, items, fleet_scan.SEEDS, 70000)


def prepare_tier_speeds_jiang(study):
    """Tier-speed study in the Jiang mass scenario (directory `tier_speeds_jiang`): 425 t at 10/5 km/h, 500 t and `MX1` (every
    member) at 12/5 km/h in the two Jiang-scenario conditions of the tier-speed study (`jiang_short_baseline`,
    `jiang_massdep_baseline`); start = main-study count + 1; seeds and rules as in the tier-speed study."""
    import csv
    sys.path.insert(0, str(PAPER / 'tier_speed_setup'))
    import tier_speed_setup as X
    X.init()
    k = {(r['cell'], r['family']): int(r['K_final'])
         for r in csv.DictReader(open(STUDY_ROOT / 'results' / 'main_fleets.csv', encoding='utf-8-sig'))}
    items = [('tierspeed_%s_%s' % (cell, tname(t)), cell, t, {'speed': key}, k[cell, t] + 1)
             for cell in ('jiang_short_baseline', 'jiang_massdep_baseline') for t, key in (('425', 'tier380'), ('500', 'tier550'), ('MX1', 'tier550'))]
    build(study, items, fleet_scan.SEEDS, 70000)


def prepare_delta_axis(study):
    """Coupling time between the levels 0 and 10 min of the one-factor sensitivity study (directory `delta_axis`): delta = 2.5
    and 5 min in `jiang_short_baseline`, for the five fleets of that study and `MX1` (the main-grid winner of that condition
    under shift staffing); start = main-study count; seeds as in the one-factor study."""
    import csv
    k = {(r['cell'], r['family']): int(r['K_final'])
         for r in csv.DictReader(open(STUDY_ROOT / 'results' / 'main_fleets.csv', encoding='utf-8-sig'))}
    cell = 'jiang_short_baseline'
    items = [('delta%g_%s_%s' % (d, cell, tname(t)), cell, t, dict(delta_min=d), k[cell, t])
             for d in (2.5, 5) for t in ('270', '300', '380', '550', 'MX2', 'MX1')]
    build(study, items, fleet_scan.SEEDS, 60000)


def prepare_delta_axis_mix(study):
    """`MX1` at the coupling times 0, 20, 30 and 40 min of the one-factor sensitivity study in `jiang_short_baseline` (directory
    `delta_axis_mix`), so that every level of that axis compares the same six fleets (10 min: main-study runs); start =
    main-study count; seeds as in the one-factor study."""
    import csv
    k = {(r['cell'], r['family']): int(r['K_final'])
         for r in csv.DictReader(open(STUDY_ROOT / 'results' / 'main_fleets.csv', encoding='utf-8-sig'))}
    cell = 'jiang_short_baseline'
    items = [('delta%g_%s_MX1' % (d, cell), cell, 'MX1', dict(delta_min=d), k[cell, 'MX1']) for d in (0, 20, 30, 40)]
    build(study, items, fleet_scan.SEEDS, 60000)


def prepare_heavy_share(study):
    sys.path.insert(0, str(PAPER / 'heavy_share'))
    import heavy_share_setup as X
    X.init()                                  # heavy-block share mass sampler; its seeds start at 301
    ks = summary_k(PAPER / 'runs/earlier_heavy_share/summary.jsonl')
    items = []
    for p in X.PS:
        for hs in X.HS:
            for t in X.TYPES:
                name = '%s_%s_%s_%s' % (X.scen(p), hs, X.DK, tname(t))
                items.append((name, '%s_%s_%s' % (X.scen(p), hs, X.DK), t, None, (ks.get(name) or 10)))
    build(study, items, list(range(301, 331)), 80000)


def case_seeds():
    return [w * 10 + d + 1 for w in CASE_WEEKS for d in range(5)]


def liu_closure(D):
    """Shortest-path closure of Liu's Table 5, in place. Returns the changed entries."""
    n, old = len(D), [row[:] for row in D]
    for m in range(n):
        for i in range(n):
            for j in range(n):
                D[i][j] = min(D[i][j], D[i][m] + D[m][j])
    return [(i, j, old[i][j], D[i][j]) for i in range(n) for j in range(n) if old[i][j] != D[i][j]]


def prepare_second_case(study):
    fleet_scan._paper_path()
    sys.path.insert(0, str(PAPER / 'code' / 'instances'))
    import liu_data as L
    import liu_days as C
    from instance_setup import k_star
    changed = liu_closure(L.DIST)                   # liu_days reads liu_data.DIST at call time
    n = len(L.DIST)
    assert all(L.DIST[i][k] <= L.DIST[i][j] + L.DIST[j][k] for i in range(n) for j in range(n) for k in range(n))
    runs = [{k: (v if k == 'model' else json.loads(v)) for k, v in row.items()}
            for row in csv.DictReader(open(ROOT / 'data/second_case_extension_runs.csv', encoding='utf8'))]

    def old_nstar(k, m, X):                         # as liu_days.summary: mean weekly on-time rate over 5 seeds
        on = {}
        for na in range(7):
            rs = [r for r in runs if (r['k'], r['model'], r['X'], r['n_add']) == (k, m, X if na else 0, na)]
            if len(rs) == 5:
                on[na] = sum(r['on_time'] / r['n'] for r in rs) / 5
        return k_star(on, 0.95)
    scratch = {(r['k'], r['X']): r['K_star']['0.95'] for r in
               json.loads((PAPER / 'runs/second_case_scan/scratch.json').read_text(encoding='utf8')) if r['model'] == 'flex'}
    bases = {}
    for k in CASE_KS:
        for model in ('flex', 'nocoup'):
            b, tot = {}, 0
            for w in CASE_WEEKS:
                tasks, W = C.sample_week(k, w)
                for day in range(5):
                    d = C.day_instance(tasks, W, day, [0] * fleet_scan.KMAX_BASE)
                    s = w * 10 + day + 1
                    d['name'] = 'yard2_k%d_%s_s%d' % (k, model, s)
                    d['vehicles'] = [{'id': v['id']} for v in d['vehicles']]
                    d['meta'].pop('load_index', None)
                    d['meta']['distance'] = 'Liu 2022 Table 5, shortest-path closure'
                    if model == 'nocoup':
                        d['meta']['max_team'] = 1
                    p = study / 'base' / ('%s.json' % d['name'])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if not p.exists():
                        p.write_text(json.dumps(d, separators=(',', ':')), encoding='utf8')
                    b[str(s)] = p.relative_to(study).as_posix()
                    tot += len(d['tasks'])
            bases[k, model] = b, tot
    specs = []
    for k in CASE_KS:
        for model, old in (('flex', 'flex'), ('nocoup', 'rigid')):
            b, tot = bases[k, model]
            for X in (250, 270, 380, 420):
                n0 = old_nstar(k, old, X)
                specs.append(dict(name='yard2_k%d_%s_ADD%d' % (k, model, X), cell='yard2_k%d_%s' % (k, model), family='ADD%d' % X,
                                  K_start=len(LIU_FLEET) + (6 if n0 is None else n0), K_min=len(LIU_FLEET), objective='cap',
                                  tmax_s=7200, seed_offset=90000, gen=None, base=b, seeds=case_seeds(), n_total=tot))
    for k in (6, 8):
        b, tot = bases[k, 'flex']
        for X in ('200', '250', '270', '300', '325', '380', '425', '500', '550', 'MX1', 'MX2'):
            specs.append(dict(name='yard2_k%d_flex_%s' % (k, tname(X)), cell='yard2_k%d_flex' % k, family=X,
                              K_start=max(scratch[k, X], kmin_of(X)), K_min=kmin_of(X), objective='cap', tmax_s=7200,
                              seed_offset=90000, gen=None, base=b, seeds=case_seeds(), n_total=tot))
    fleet_scan.write_series(study, specs)
    (study / 'distance_closure.json').write_text(json.dumps(changed) + '\n', encoding='utf8')


def prepare_overweight_only(study):
    """The 72 mix series of the main study under overweight-only coupling (directory `overweight_only`)."""
    fleet_scan._paper_path()
    main_counts = json.loads((STUDY_ROOT / 'main' / 'series.json').read_text(encoding='utf8'))
    rig = {(o['cell'], o['family']): int(o['K_start']) for o in
           csv.DictReader(open(STUDY_ROOT / 'results/overweight_only_fleets.csv', encoding='utf-8-sig'))}
    specs, bases = [], {}
    for sp in main_counts:
        if not sp['family'].startswith('MX'):
            continue
        cell = sp['cell']
        if cell not in bases:
            bases[cell] = {str(s): fleet_scan.make_base(study, cell, s) for s in fleet_scan.SEEDS}
        specs.append(dict(sp, name=sp['name'] + '_rigid', K_start=max(sp['K_start'], rig.get((cell, sp['family'])) or 0),
                          seed_offset=45000, base=bases[cell]))
    fleet_scan.write_series(study, specs)


def prepare_exact(study):
    """Exact comparison on single-batch instances (directory `exact`): single-batch slices of seeds 101-110 (the
    'study' slices of exact_slices.py), 8 common families plus the two `L300_H425` mixes in the cells of the Liu
    mass scenario (`liu`); scan from the structural floor to floor + 8; seeds s + 200000 + 1000 j."""
    import exact_slices as V
    index = json.loads((study / 'slices_study.json').read_text(encoding='utf8'))
    cells = json.loads((study / 'params.json').read_text(encoding='utf8'))['cells']      # tier fixed by the pilot
    specs = []
    for cell in cells:
        rows = [r for r in index if r['cell'] == cell]
        assert sorted(r['seed'] for r in rows) == V.SEEDS['study'], cell
        slices = {r['seed']: json.loads((study / r['file']).read_text(encoding='utf8')) for r in rows}
        for fam in V.families(cell):
            k0 = max(V.k_lb(d, fam) for d in slices.values())
            specs.append(dict(name='exact_%s_%s' % (cell, tname(fam)), cell=cell, family=fam, K_start=k0, K_min=k0, hi_limit=k0 + 8,
                              objective='cap', tmax_s=7200, seed_offset=200000, gen=None,
                              base={str(r['seed']): r['file'] for r in rows}, seeds=V.SEEDS['study'],
                              n_total=sum(len(d['tasks']) for d in slices.values())))
    fleet_scan.write_series(study, specs)


def work(job):
    """fleet_scan.work with the coupling rule taken from the series name ('_rigid' -> overweight-only)."""
    if not job['series'].endswith('_rigid'):
        return fleet_scan.work(job)
    import time
    for sub in ('common', 'search'):
        if str(fleet_scan.SOLVER / sub) not in sys.path:
            sys.path.insert(0, str(fleet_scan.SOLVER / sub))
    from core import Inst, evaluate
    from alns import alns
    mode = 'rigid'
    study = Path(job['study'])
    out = study / 'runs' / job['series'] / ('K%d_s%d_j%d.json' % (job['K'], job['seed'], job['j']))
    t0 = time.perf_counter()
    d = json.loads((study / job['base']).read_text(encoding='utf8'))
    K = job['K']
    d['vehicles'] = [dict(d['vehicles'][k], cap=c) for k, c in enumerate(job['caps'])]
    d['tauE_start'] = d['tauE_start'][:K]
    d['meta'].update(objective_mode=job['objective'], tmax_s=job['tmax_s'], crew_team=None)
    d['name'] = '%s_K%d_s%d' % (job['series'], K, job['seed'])
    inst = Inst(d)
    res = dict(job=job, mode=mode)
    if any(not inst.teams(i, mode) for i in range(inst.n)):
        res.update(status='STRUCTURALLY_INFEASIBLE')
    else:
        cfg = {k: v for k, v in json.loads((fleet_scan.SOLVER / 'search' / 'config.json').read_text(encoding='utf8')).items()
               if not k.startswith('_')}
        cfg['time_limit'] = float('inf')
        r = alns(inst, 0, mode, seed=job['seed'] + job['seed_offset'] + 1000 * job['j'], cfg=cfg, checkpoints=fleet_scan.CP)
        team = {int(i): tuple(v) for i, v in r['team'].items()}
        ev = evaluate(inst, r['order'], team, 0, detail=True)
        late = [ev['comp'][i] - inst.due[i] for i in range(inst.n)]
        d2 = json.loads(json.dumps(d))
        d2['meta']['crew_team'] = {1: 4, 2: 4, 3: 4}
        evt = evaluate(Inst(d2), r['order'], team, 0)
        last = [max((ev['comp'][i] for i in q), default=0) for q in ev['seqs']]
        res.update(status='OK', on_time=sum(x <= 0 for x in late), max_tard=max(0, max(late)),
                   n_over=sum(x > job['tmax_s'] for x in late) if job['tmax_s'] else 0,
                   crew_veh_h=ev['crew_s'] / 3600, crew_team_h=evt['crew_s'] / 3600,
                   after_h=sum(max(0, c - 16 * 3600) for c in last) / 3600, n_coop=ev['n_coop'],
                   iters=r['iters'], time_limit_reached=r['iters'] < cfg['max_iter'],
                   checkpoints=r['checkpoints'], order=r['order'], team={i: list(v) for i, v in team.items()})
    res['wall_s'] = time.perf_counter() - t0
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.tmp')
    tmp.write_text(json.dumps(res) + '\n', encoding='utf8')
    tmp.replace(out)
    return job['series'], job['K'], job['seed'], job['j']


def run(study, workers):
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)      # children inherit on Windows
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    fleet_scan.SEEDS = specs[0].get('seeds', fleet_scan.SEEDS)                 # used only in this (parent) process
    if any(sp['name'].endswith('_rigid') for sp in specs):
        fleet_scan.work = work                                            # submitted by reference to this module
    fleet_scan.run(study, workers)


if __name__ == '__main__':
    cmd, study = sys.argv[1], STUDY_ROOT / sys.argv[2]
    if cmd == 'run':
        run(study, int(sys.argv[3]) if len(sys.argv) > 3 else 8)
    else:
        {'prepare-sensitivity': prepare_sensitivity, 'prepare-delta-axis': prepare_delta_axis, 'prepare-delta-axis-mix': prepare_delta_axis_mix, 'prepare-tier-speeds': prepare_tier_speeds, 'prepare-tier-speeds-jiang': prepare_tier_speeds_jiang, 'prepare-heavy-share': prepare_heavy_share, 'prepare-second-case': prepare_second_case,
         'prepare-overweight-only': prepare_overweight_only, 'prepare-exact': prepare_exact}[cmd](study)
