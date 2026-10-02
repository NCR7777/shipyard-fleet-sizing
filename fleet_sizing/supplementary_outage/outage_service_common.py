"""Shared helpers of supplementary_outage (service lost with one transporter out, directory `outage`; on-time targets of 90% and 98%,
directories `service90`, `service98`): reading the design files, run summaries from the compact run tables of the main results
and from run files, a file-integrity record of the supplementary_outage scripts themselves, and a low-priority process pool for
fleet_scan.work jobs."""
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
for p in (str(STUDY_ROOT / 'code'), str(STUDY_ROOT / 'supplementary')):
    if p not in sys.path:
        sys.path.insert(0, p)
import compat                                             # noqa: E402,F401  (psutil constant off Windows)

SEEDS = list(range(101, 131))
NTOT = 97 * len(SEEDS)
PRE = HERE / 'design'


def design(name):
    return json.loads((PRE / name).read_text(encoding='utf8'))


def summ_json(r):
    if r.get('status') != 'OK':
        return None
    return dict(on=r['on_time'], over=r['n_over'], crew_veh=r['crew_veh_h'], crew_team=r['crew_team_h'], after=r['after_h'],
                coop=r['n_coop'])


def compact_runs(names):
    """series name -> {(K, seed, j): summary or None} from `results/runs_compact/main.csv` and `delay_cap.csv`."""
    names, out = set(names), {}
    for f in ('main.csv', 'delay_cap.csv'):
        with open(RES / 'runs_compact' / f, encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                if r['series'] not in names:
                    continue
                v = None if r['status'] != 'OK' else dict(
                    on=int(r['on_time']), over=int(r['n_over']), crew_veh=float(r['crew_veh_h']), crew_team=float(r['crew_team_h']),
                    after=float(r['after_h']), coop=int(r['n_coop']))
                out.setdefault(r['series'], {})[int(r['K']), int(r['seed']), int(r['j'])] = v
    return out


def json_runs(study, name):
    out = {}
    d = study / 'runs' / name
    if d.exists():
        for p in d.glob('*.json'):
            r = json.loads(p.read_text(encoding='utf8'))
            j = r['job']
            out[j['K'], j['seed'], j['j']] = summ_json(r)
    return out


def self_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze_self(study, files):
    """File-integrity record like the one written by `fleet_scan.freeze`, for the supplementary_outage scripts that define a study (their
    logic is not covered by `FREEZE.json`): script hashes are written when the study starts and must match on resume."""
    h = {Path(f).name: self_hash(f) for f in files}
    p = study / 'SUPP2_FREEZE.json'
    if p.exists():
        assert json.loads(p.read_text(encoding='utf8')) == h, 'supplementary_outage scripts changed since this study started; refusing to resume'
    else:
        p.write_text(json.dumps(h, indent=1) + '\n', encoding='utf8')


def need(p, ntot=NTOT):
    return math.ceil(p * ntot - 1e-9)


def write_csv(path, rows):
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def copy_base(src_study, dst_study, base):
    import shutil
    for rel in base.values():
        q = dst_study / rel
        if not q.exists():
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_study / rel, q)


def run_jobs(study, jobs, workers):
    """fleet_scan.work over the jobs (skipping those already written), low priority, spawn context as in fleet_scan.run."""
    import multiprocessing as mp
    import time
    import traceback
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import psutil
    import fleet_scan
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    todo = [j for j in jobs if not (study / 'runs' / j['series'] / ('K%d_s%d_j%d.json' % (j['K'], j['seed'], j['j']))).exists()]
    t0, done, err = time.time(), 0, 0
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
        futs = {pool.submit(fleet_scan.work, j): j for j in sorted(todo, key=lambda x: -x['K'])}
        for f in as_completed(futs):
            try:
                f.result()
                done += 1
            except Exception:
                err += 1
                (study / 'errors.log').open('a', encoding='utf8').write(traceback.format_exc() + '\n')
            (study / 'progress.json').write_text(json.dumps(dict(done=done, errors=err, todo=len(todo), total=len(jobs),
                                                                 started=t0, updated=time.time())), encoding='utf8')
    print(json.dumps(dict(finished=True, runs=done, errors=err, skipped=len(jobs) - len(todo))), flush=True)
