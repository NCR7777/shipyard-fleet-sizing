"""Adaptive, symmetric fleet-count scans on 30 instances.

A study directory holds series.json (one spec per fleet series), base/ (one instance per
(instance key, seed) with 40 start positions; a fleet uses the first K), runs/<series>/K<k>_s<seed>_j<j>.json,
`FREEZE.json` (hashes of series.json, the code and the solver configuration; a restart refuses to
resume if they changed) and progress.json. Every series advances on its own:
  scan: K_S and K_S-1 (j=0) -> up to K_S+4 if K_S fails / down while K-1 qualifies ->
        upward extension (j=0) until the construction-only checkpoint qualifies (search-intensity levels) ->
  boundary: j=1,2 at K*-1; if it then qualifies K* drops and K*-1 is checked once more.
Qualification (own runs only, lower counts embedded): every instance has a run with no block over
the cap, and the on-time total over the instances is at least ceil(0.95 * n * instances).

  python fleet_scan.py prepare-main | prepare-delay-cap <study>      # write series.json and base instances
  python fleet_scan.py run <study> [workers]                  # restartable
"""
import hashlib
import json
import math
import multiprocessing as mp
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STUDY_ROOT = ROOT / 'fleet_sizing'
SOLVER = STUDY_ROOT / 'solver'      # faster version of the solver package (`solver_reference`), identical results
SEEDS = list(range(101, 131))
KMAX_BASE = 40
CP = (0, 100, 300)


# ---------------------------------------------------------------- preparation (main process)
def _paper_path():
    for sub in ('common', 'search', 'instances'):
        p = str(ROOT / 'paper' / 'code' / sub)
        if p not in sys.path:
            sys.path.insert(0, p)


def caps_of(fam, K):
    if fam.startswith('L'):
        light, rest = fam[1:].split('_H')
        heavy, h = rest.split('x')
        return [int(heavy)] * int(h) + [int(light)] * (K - int(h))
    if fam.startswith('MX'):
        h = int(fam[-1])
        return [550] * h + [270] * (K - h)
    return [int(fam)] * K


def kmin_of(fam):
    if fam.startswith('L'):
        return int(fam.split('x')[-1]) + 1
    if fam.startswith('MX'):
        return int(fam[-1]) + 1
    return 3


def make_base(study, cell, seed, gen=None):
    """Base instance for (cell, gen) with KMAX_BASE start positions."""
    import instance_setup as E
    ms, hs, dk = cell.split('_')
    d = E.make('550', KMAX_BASE, ms, hs, dk, seed, gen=gen)
    d['tasks'] = [{k: t[k] for k in ('id', 'mass', 'release', 'due', 'load', 'unload', 'tauL', 'turns')} for t in d['tasks']]
    d['vehicles'] = [{'id': v['id']} for v in d['vehicles']]
    d['meta'].pop('note', None)
    d['meta'].pop('load_index', None)
    key = '%s__%s' % (cell, json.dumps(gen, sort_keys=True) if gen else 'base')
    p = study / 'base' / ('%s_s%d.json' % (hashlib.sha1(key.encode()).hexdigest()[:12], seed))
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(json.dumps(d, separators=(',', ':')), encoding='utf8')
    return p.relative_to(study).as_posix()


def check_prefix(cell, seed, fam, K, gen=None):
    """The fleet's own instance must equal the base instance restricted to K start positions."""
    import instance_setup as E
    ms, hs, dk = cell.split('_')
    a = E.make(fam if not fam.startswith('L') else '550', K, ms, hs, dk, seed, caps=caps_of(fam, K), gen=gen)
    b = E.make('550', KMAX_BASE, ms, hs, dk, seed, gen=gen)
    assert [t['release'] for t in a['tasks']] == [t['release'] for t in b['tasks']]
    assert [t['mass'] for t in a['tasks']] == [t['mass'] for t in b['tasks']]
    assert a['tauE'] == b['tauE'] and a['tauE_start'] == b['tauE_start'][:K]
    assert [t['load'] + t['tauL'] + t['unload'] for t in a['tasks']] == [t['load'] + t['tauL'] + t['unload'] for t in b['tasks']]


def write_series(study, specs):
    study.mkdir(parents=True, exist_ok=True)
    (study / 'series.json').write_text(json.dumps(specs, indent=1) + '\n', encoding='utf8')
    print(json.dumps(dict(study=study.name, series=len(specs))), flush=True)


def prepare_main(study):
    _paper_path()
    known = json.loads((ROOT / 'earlier_study/results/pooled_counts_tmax120.json').read_text(encoding='utf8'))
    specs, bases = [], {}
    for o in known:
        cell, fam = o['cell'], o['family']
        if cell not in bases:
            bases[cell] = {str(s): make_base(study, cell, s) for s in SEEDS}
        specs.append(dict(name='%s_%s' % (cell, fam), cell=cell, family=fam, K_start=o['K_known'], K_min=kmin_of(fam),
                          objective='cap', tmax_s=7200, seed_offset=40000, gen=None, base=bases[cell]))
    for cell, fam, K in (('liu_short_baseline', '425', 5), ('extraheavy_massdep_tight', 'MX2', 13), ('rohcha_massdep_baseline', '200', 27)):
        for s in (101, 125):
            check_prefix(cell, s, fam, K)
    write_series(study, specs)


def prepare_delay_cap(study):
    _paper_path()
    sys.path.insert(0, str(ROOT / 'earlier_study' / 'code'))
    levels = [('inf', None), ('480', 480), ('240', 240), ('120', 120), ('60', 60), ('30', 30)]
    heavy = {'jiang_short_baseline': 500, 'uniform_short_baseline': 500, 'liu_short_baseline': 425}
    fams = {}
    for cell, qh in heavy.items():
        fams[cell] = ['200', '250', '270', '300', '325', '380', '425', '500', '550', 'MX1', 'MX2'] + \
            ['L%d_H%dx%d' % (ql, qh, h) for ql in (270, 300) for h in ((1, 2, 3, 4) if cell.startswith('liu') else (1, 2, 3))]
    start = json.loads((STUDY_ROOT / 'results' / 'delay_cap_start_counts.json').read_text(encoding='utf8'))
    bases = {cell: {str(s): make_base(study, cell, s) for s in SEEDS} for cell in heavy}
    specs = []
    for li, (lev, tmin) in enumerate(levels):
        for cell, fl in fams.items():
            for fam in fl:
                K0 = start['%s|%s|%s' % (lev, cell, fam)]
                if K0 is None:
                    continue
                specs.append(dict(name='T%s_%s_%s' % (lev, cell, fam), cell=cell, family=fam, K_start=K0,
                                  K_min=kmin_of(fam), objective='service' if tmin is None else 'cap',
                                  tmax_s=None if tmin is None else 60 * tmin, seed_offset=50000 + 10000 * li, gen=None,
                                  base=bases[cell], level=lev))
    write_series(study, specs)


# ---------------------------------------------------------------- worker (solver package only)
def work(job):
    for sub in ('common', 'search'):
        if str(SOLVER / sub) not in sys.path:
            sys.path.insert(0, str(SOLVER / sub))
    from core import Inst, evaluate
    from alns import alns
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
    res = dict(job=job)
    if any(not inst.teams(i, 'flex') for i in range(inst.n)):
        res.update(status='STRUCTURALLY_INFEASIBLE')
    else:
        cfg = {k: v for k, v in json.loads((SOLVER / 'search' / 'config.json').read_text(encoding='utf8')).items() if not k.startswith('_')}
        cfg['time_limit'] = float('inf')         # count budget only (5,000 constructions, 786 iterations)
        r = alns(inst, 0, 'flex', seed=job['seed'] + job['seed_offset'] + 1000 * job['j'], cfg=cfg, checkpoints=CP)
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


# ---------------------------------------------------------------- series state machine
class Series:
    def __init__(self, spec, study, n_tasks=97):
        self.s, self.study = spec, study
        self.need = math.ceil(0.95 * n_tasks * len(SEEDS) - 1e-9)
        self.runs = {}                     # (K, seed, j) -> summary
        self.pending = set()
        self.phase, self.rounds, self.kstar = 'scan', 0, None
        self.hi_limit = spec['K_start'] + 4

    def load(self):
        d = self.study / 'runs' / self.s['name']
        if d.exists():
            for p in d.glob('*.json'):
                r = json.loads(p.read_text(encoding='utf8'))
                j = r['job']
                self.runs[j['K'], j['seed'], j['j']] = self._summ(r)

    @staticmethod
    def _summ(r):
        if r['status'] != 'OK':
            return None
        return dict(on=r['on_time'], over=r['n_over'], cps=[(c['it'], c['on_time'], c.get('n_over', 0)) for c in r['checkpoints']])

    def add(self, K, seed, j):
        p = self.study / 'runs' / self.s['name'] / ('K%d_s%d_j%d.json' % (K, seed, j))
        self.runs[K, seed, j] = self._summ(json.loads(p.read_text(encoding='utf8')))
        self.pending.discard((K, seed, j))

    def tested(self):
        return sorted({K for (K, s, j) in self.runs})

    def complete(self, K, js=(0,)):
        return all((K, s, j) in self.runs for s in SEEDS for j in js)

    def qualifies(self, K, level=None):
        """level None: full runs (any j); level it: checkpoint `it` of j=0 runs."""
        tot = 0
        for s in SEEDS:
            best = None
            for (k, ss, j), v in self.runs.items():
                if ss != s or k > K or v is None:
                    continue
                if level is None:
                    cand = (v['over'] == 0, v['on'])
                else:
                    if j != 0:
                        continue
                    c = next((c for c in v['cps'] if c[0] == level), None)
                    if c is None:
                        continue
                    cand = (c[2] == 0, c[1])
                if cand[0] and (best is None or cand[1] > best):
                    best = cand[1]
            if best is None:
                return False
            tot += best
        return tot >= self.need

    def jobs_for(self, K, js):
        out = []
        for j in js:
            for s in SEEDS:
                if (K, s, j) not in self.runs and (K, s, j) not in self.pending:
                    self.pending.add((K, s, j))
                    out.append(dict(series=self.s['name'], K=K, seed=s, j=j, caps=caps_of(self.s['family'], K),
                                    base=self.s['base'][str(s)], objective=self.s['objective'], tmax_s=self.s['tmax_s'],
                                    seed_offset=self.s['seed_offset'], study=str(self.study)))
        return out

    def next_jobs(self):
        """Advance the state machine; return new jobs ([] while waiting; None when finished)."""
        if self.pending:
            return []
        Ks, lo = self.s['K_start'], max(self.s['K_min'], self.s['K_start'] - 1)
        if self.phase == 'scan':
            init = [K for K in sorted({lo, Ks}) if not self.complete(K)]
            if init:
                return [j for K in init for j in self.jobs_for(K, (0,))]
            t = [K for K in self.tested() if self.complete(K)]
            hi, low = max(t), min(t)
            if not self.qualifies(hi) and hi < self.hi_limit:
                return self.jobs_for(hi + 1, (0,))
            if self.qualifies(low) and low > self.s['K_min']:
                return self.jobs_for(low - 1, (0,))
            if not self.qualifies(hi, level=0) and hi < self.hi_limit:
                return self.jobs_for(hi + 1, (0,))
            q = [K for K in t if self.qualifies(K)]
            if not q:
                self.phase = 'done'
                return None
            self.kstar, self.phase = min(q), 'boundary'
        if self.phase == 'boundary':
            b = self.kstar - 1
            if b < self.s['K_min'] or self.rounds >= 2:
                self.phase = 'done'
                return None
            if not self.complete(b, (0, 1, 2)):
                return self.jobs_for(b, (0, 1, 2))
            self.rounds += 1
            if self.qualifies(b):
                self.kstar = b
                return self.next_jobs()
            self.phase = 'done'
            return None
        return None


def freeze(study):
    files = [study / 'series.json', Path(__file__), SOLVER / 'search' / 'config.json'] + sorted(SOLVER.rglob('*.py'))
    h = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    fz = study / 'FREEZE.json'
    if fz.exists():
        assert json.loads(fz.read_text(encoding='utf8')) == h, 'hashed input files changed; refusing to resume'
    else:
        fz.write_text(json.dumps(h, indent=1) + '\n', encoding='utf8')


def run(study, workers):
    freeze(study)
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    series = {}
    for sp in specs:
        S = Series(sp, study)
        S.load()
        series[sp['name']] = S
    # rebuild state machines from existing runs (restart)
    queue = []
    for S in series.values():
        queue += S.next_jobs() or []          # one call advances through all immediate transitions
    t0, done, errors = time.time(), 0, 0
    finished = sum(S.phase == 'done' for S in series.values())

    def prog():
        (study / 'progress.json').write_text(json.dumps(dict(
            done_runs=sum(len(S.runs) for S in series.values()), running_or_queued=sum(len(S.pending) for S in series.values()),
            series=len(series), series_done=sum(S.phase == 'done' for S in series.values()),
            est_total_runs=len(series) * 4 * len(SEEDS), started=t0, updated=time.time())), encoding='utf8')

    queue.sort(key=lambda j: -j['K'])
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
        futs = {pool.submit(work, j): j for j in queue}
        prog()
        while futs:
            ready, _ = wait(list(futs), return_when=FIRST_COMPLETED)
            for f in ready:
                j = futs.pop(f)
                S = series[j['series']]
                try:
                    f.result()
                    S.add(j['K'], j['seed'], j['j'])
                    done += 1
                except BrokenProcessPool:         # a worker died: stop instead of logging every pending job
                    raise
                except Exception:
                    errors += 1
                    S.pending.discard((j['K'], j['seed'], j['j']))
                    (study / 'errors.log').open('a', encoding='utf8').write(traceback.format_exc() + '\n')
                    continue
                js = S.next_jobs()                # [] while other runs of the stage are pending
                for nj in sorted(js or [], key=lambda x: -x['K']):
                    futs[pool.submit(work, nj)] = nj
            prog()
    prog()
    print(json.dumps(dict(finished=True, runs=done, errors=errors)), flush=True)


if __name__ == '__main__':
    cmd, study = sys.argv[1], STUDY_ROOT / sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == 'prepare-main':
        prepare_main(study)
    elif cmd == 'prepare-delay-cap':
        prepare_delay_cap(study)
    elif cmd == 'run':
        run(study, int(sys.argv[3]) if len(sys.argv) > 3 else 20)
