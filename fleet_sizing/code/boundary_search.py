"""Boundary search (directory `boundary_search`): three times the search at one transporter fewer for the fleets nearest to a
search-dependent decision, near challengers and incumbents alike, plus ten strong controls.

Selection (result files only): challengers = series graded weak or medium (grading_series.csv) that are in the flip list
of a search-dependent decision (main_decisions.csv); incumbents = the winners of the decisions they can flip;
controls = 10 series graded strong that are in a flip list but in neither group, drawn with random.Random(CONTROL_SEED).
Runs: at K* - 1, j = 3..8 for each of the 30 instances (main-study instances, seed rule and budget: instance seed +
40000 + 1000 j); a series that then qualifies at K* - 1 with all its runs gets one round at K* - 2 (j = 0..8 where
missing). New runs go to `fleet_sizing/boundary_search/runs/<series>/`.
Analysis: the new count is the smallest qualifying complete count over the series' main-study and new runs
(analyse_study rules: lower counts embedded, own runs only), priced by the same knapsack; all 6,480 decisions are
recomputed with the new rows. Reported: series that lost a transporter by group (light <= 325 t, heavy, mixes),
decisions whose cheapest fleet changed, share of settings whose cheapest fleet couples at most one block in ten (all,
outside the extra-heavy scenario) next to the reported share, controls that lost a transporter.

  python boundary_search.py select                 -> boundary_search/selection.json
  pypy boundary_search.py run <workers>            # round 1, then round 2 for the series that qualify at K* - 1
  python boundary_search.py analyse                -> results/boundary_search_series.csv, results/boundary_search_summary.json
"""
import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
MAIN_DIR, BOUNDARY_DIR, RES = STUDY_ROOT / 'main', STUDY_ROOT / 'boundary_search', STUDY_ROOT / 'results'
sys.path.insert(0, str(HERE))
import analyse_study as A                                     # noqa: E402

SEEDS = list(range(101, 131))
NEED = math.ceil(0.95 * 97 * 30 - 1e-9)
CONTROL_SEED, N_CONTROL = 20261002, 10
NEW_J = range(3, 9)


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def select():
    grade = {(r['cell'], r['family']): r['grade'] for r in rcsv(RES / 'grading_series.csv')}
    flip = defaultdict(list)
    for d in rcsv(RES / 'main_decisions.csv'):
        if d['status'] == 'search-dependent':
            for f in d['flip_by'].split():
                flip[d['cell'], f].append(d)
    chal = {k for k in flip if grade.get(k) in ('weak', 'medium')}
    inc = {(d['cell'], d['winner']) for k in chal for d in flip[k]}
    pool = sorted(k for k in flip if grade.get(k) == 'strong' and k not in chal | inc)
    ctrl = set(random.Random(CONTROL_SEED).sample(pool, N_CONTROL))
    role = lambda k: 'challenger and incumbent' if k in chal and k in inc else ('challenger' if k in chal else
                                                                                ('incumbent' if k in inc else 'control'))
    sel = [dict(series='%s_%s' % k, cell=k[0], family=k[1], role=role(k), grade=grade[k]) for k in sorted(chal | inc | ctrl)]
    BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
    (BOUNDARY_DIR / 'selection.json').write_text(json.dumps(sel, indent=1) + '\n', encoding='utf8')
    print(json.dumps(dict(Counter(x['role'] for x in sel)), indent=1))


def specs():
    sel = {x['series']: x for x in json.loads((BOUNDARY_DIR / 'selection.json').read_text(encoding='utf8'))}
    kf = {r['series']: int(r['K_final']) for r in rcsv(RES / 'main_fleets.csv')}
    return [dict(sp, K_star=kf[sp['name']], role=sel[sp['name']]['role'])
            for sp in json.loads((MAIN_DIR / 'series.json').read_text(encoding='utf8')) if sp['name'] in sel]


def merged(sp):
    return {**A.load(MAIN_DIR, sp), **A.load(BOUNDARY_DIR, sp)}


def jobs(sp, K, js):
    import fleet_scan
    if K < sp['K_min']:
        return []
    return [dict(series=sp['name'], K=K, seed=s, j=j, caps=fleet_scan.caps_of(sp['family'], K), base='../main/' + sp['base'][str(s)],
                 objective=sp['objective'], tmax_s=sp['tmax_s'], seed_offset=sp['seed_offset'], study=str(BOUNDARY_DIR))
            for s in SEEDS for j in js
            if not (BOUNDARY_DIR / 'runs' / sp['name'] / ('K%d_s%d_j%d.json' % (K, s, j))).exists()
            and not (MAIN_DIR / 'runs' / sp['name'] / ('K%d_s%d_j%d.json' % (K, s, j))).exists()]


def run(workers):
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    import psutil
    import fleet_scan
    p = psutil.Process()
    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    p.cpu_affinity(list(range(1, psutil.cpu_count())))
    sps = specs()
    for rnd in (1, 2):
        if rnd == 1:
            js = [j for sp in sps for j in jobs(sp, sp['K_star'] - 1, NEW_J)]
        else:
            js = [j for sp in sps if A.qualifies(merged(sp), sp['K_star'] - 1, 'final', NEED)
                  for j in jobs(sp, sp['K_star'] - 2, range(0, 9))]
        js.sort(key=lambda j: -j['K'])
        with ProcessPoolExecutor(workers, mp_context=mp.get_context('spawn')) as ex:
            for i, _ in enumerate(ex.map(fleet_scan.work, js), 1):
                if i % 50 == 0 or i == len(js):
                    (BOUNDARY_DIR / 'progress.json').write_text(json.dumps(dict(round=rnd, done=i, total=len(js))) + '\n', encoding='utf8')
        print(json.dumps(dict(round=rnd, runs=len(js))), flush=True)


def analyse():
    sys.path.insert(0, str(HERE))
    import cost_decisions as C
    fl = C.load(RES / 'main_fleets.csv')
    coop = {(r['cell'], r['family']): float(r['coop_share']) for r in rcsv(RES / 'main_fleets.csv')}
    fl2, coop2, rows = dict(fl), dict(coop), []
    for sp in specs():
        runs = merged(sp)
        complete = sorted(k for k in {k for (k, s, j) in runs} if all((k, s, 0) in runs for s in SEEDS))
        q = [k for k in complete if A.qualifies(runs, k, 'final', NEED)]
        k = min(q)
        ch = A.knapsack(runs, k, NEED)
        key = sp['cell'], sp['family']
        new = dict(K=k, crew_veh_h=sum(x[1] for x in ch) / 30, crew_team_h=sum(x[2] for x in ch) / 30, after_h=sum(x[3] for x in ch) / 30)
        fl2[key], coop2[key] = new, sum(x[4] for x in ch) / (97 * 30)
        rows.append(dict(series=sp['name'], cell=sp['cell'], family=sp['family'], role=sp['role'], K_star=sp['K_star'], K_new=k,
                         coop_old=coop[key], coop_new=coop2[key], new_runs=sum(1 for (kk, s, j) in A.load(BOUNDARY_DIR, sp))))
    with open(RES / 'boundary_search_series.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    args = (C.MAIN_MODELS, C.main_r(), C.LAB4)
    old, new = C.decisions(fl, *args), C.decisions(fl2, *args)
    key = lambda x: (x['cell'], x['model'], x['r'], x['labour'])
    nw = {key(x): x['winner'] for x in new}

    def share(dec, cp, outside=False):
        g = [x for x in dec if not (outside and x['cell'].startswith('extraheavy'))]
        return sum(cp[x['cell'], x['winner']] <= 0.10 for x in g) / len(g)
    group = lambda f: 'mix' if f.startswith('MX') else ('light' if int(f) <= 325 else 'heavy')
    lost = [x for x in rows if x['K_new'] < x['K_star']]
    out = dict(series=len(rows), lost_one_or_more=dict(Counter(group(x['family']) for x in lost if x['role'] != 'control')),
               controls_lost=sum(1 for x in lost if x['role'] == 'control'),
               decisions_changed=sum(nw[key(x)] != x['winner'] for x in old), settings=len(old),
               share_reported=share(old, coop), share_new=share(new, coop2),
               share_reported_outside_extra_heavy=share(old, coop, True), share_new_outside_extra_heavy=share(new, coop2, True))
    (RES / 'boundary_search_summary.json').write_text(json.dumps(out, indent=1) + '\n', encoding='utf8')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    a = sys.argv[1:]
    {'select': select, 'run': lambda: run(int(a[1])), 'analyse': analyse}[a[0]]()
