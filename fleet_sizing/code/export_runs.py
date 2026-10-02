"""Compact tables of every scheduling run and of the instance tasks, for analysis outside the run files.

Runs (one row per run file of each path-A study, the robust-sizing runs, the boundary-search runs and the
supplementary studies; a run copied unchanged from another study is listed only under that study):
  study, series, cell, family, K, seed, j, status, on_time, n_over, max_tard_s, crew_veh_h, crew_team_h, after_h,
  n_coop, iters, wall_s, and on-time / over-cap counts at the search checkpoints 0, 100 and 300 iterations.
Instance tasks (main study, heavy-share study and second case): cell, seed, task, mass_t, release_s, due_s, load_s,
  unload_s. Travel times, routes and turn counts are left out: they encode the main yard's layout.

  python export_runs.py [workers] [study ...]   -> results/runs_compact/<study>.csv, results/runs_compact/tasks_<study>.csv
"""
import csv
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
OUT = STUDY_ROOT / 'results' / 'runs_compact'
STUDIES = ('main', 'delay_cap', 'overweight_only', 'second_case', 'sensitivity', 'delta_axis', 'delta_axis_mix', 'heavy_share', 'tier_speeds', 'tier_speeds_jiang', 'robust', 'boundary_search',
           'fresh_days', 'extended_mixes', 'unresolved_scan', 'candidates_', 'candidates_handling', 'exact', 'outage', 'service90', 'service98')
SPECS_OF = {'robust': 'main', 'boundary_search': 'main'}          # these studies rerun series of the main study
COPIED_FROM = {'unresolved_scan': 'sensitivity', 'service90': 'main', 'service98': 'main'}   # their run folders start with copies of these studies' runs
CP = (0, 100, 300)
RUN_KEYS = ['study', 'series', 'cell', 'family', 'K', 'seed', 'j', 'status', 'on_time', 'n_over', 'max_tard_s', 'crew_veh_h',
            'crew_team_h', 'after_h', 'n_coop', 'iters', 'wall_s'] + ['cp%d_%s' % (c, k) for c in CP for k in ('on', 'over')]


def _series_rows(args):
    study, name, cell, family = args
    rows = []
    src = COPIED_FROM.get(study)
    for p in sorted((STUDY_ROOT / study / 'runs' / name).glob('K*_s*_j*.json')):
        q = STUDY_ROOT / src / 'runs' / name / p.name if src else None
        if q is not None and q.exists() and q.read_bytes() == p.read_bytes():
            continue
        r = json.loads(p.read_text(encoding='utf8'))
        j = r['job']
        row = dict(study=study, series=name, cell=cell, family=family, K=j['K'], seed=j['seed'], j=j['j'], status=r['status'],
                   on_time=r.get('on_time'), n_over=r.get('n_over'), max_tard_s=r.get('max_tard'), crew_veh_h=r.get('crew_veh_h'),
                   crew_team_h=r.get('crew_team_h'), after_h=r.get('after_h'), n_coop=r.get('n_coop'), iters=r.get('iters'),
                   wall_s=round(r['wall_s'], 2))
        cps = {c['it']: c for c in r.get('checkpoints') or []}
        for c in CP:
            row['cp%d_on' % c] = cps[c]['on_time'] if c in cps else None
            row['cp%d_over' % c] = cps[c].get('n_over') if c in cps else None
        rows.append(row)
    return rows


def write(path, keys, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def runs(workers, studies=STUDIES):
    for study in studies:
        specs = json.loads((STUDY_ROOT / SPECS_OF.get(study, study) / 'series.json').read_text(encoding='utf8'))
        names = {d.name for d in (STUDY_ROOT / study / 'runs').iterdir() if d.is_dir()}
        jobs = [(study, sp['name'], sp['cell'], sp['family']) for sp in specs if sp['name'] in names]
        assert len(jobs) == len(names), (study, names - {j[1] for j in jobs})
        with ProcessPoolExecutor(workers) as ex:
            rows = [r for part in ex.map(_series_rows, jobs) for r in part]
        write(OUT / ('%s.csv' % study), RUN_KEYS, rows)
        print(study, len(jobs), 'series', len(rows), 'runs', flush=True)


def tasks():
    for study in ('main', 'heavy_share', 'second_case'):
        specs = json.loads((STUDY_ROOT / study / 'series.json').read_text(encoding='utf8'))
        seen, rows = set(), []
        for sp in specs:
            for s, rel in sorted(sp['base'].items(), key=lambda x: int(x[0])):
                if (sp['cell'], s) in seen:
                    continue
                seen.add((sp['cell'], s))
                d = json.loads((STUDY_ROOT / study / rel).read_text(encoding='utf8'))
                rows += [dict(cell=sp['cell'], seed=int(s), task=t['id'], mass_t=t['mass'], release_s=t['release'], due_s=t['due'],
                              load_s=t['load'], unload_s=t['unload']) for t in d['tasks']]
        write(OUT / ('tasks_%s.csv' % study), ['cell', 'seed', 'task', 'mass_t', 'release_s', 'due_s', 'load_s', 'unload_s'], rows)
        print('tasks', study, len(seen), 'instances', len(rows), 'tasks', flush=True)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    runs(int(sys.argv[1]) if len(sys.argv) > 1 else 8, tuple(sys.argv[2:]) or STUDIES)
    if len(sys.argv) <= 2:
        tasks()
