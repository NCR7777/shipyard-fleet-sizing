"""Fleet-count analysis of a study: counts per search-intensity level, pricing
selection by multiple-choice knapsack, fleet table for costing. Works on a partial study (series
whose scan has not finished are marked).

Levels: final (all runs of the series, lower counts embedded) = K*; single (j = 0 runs only);
cp0 / cp100 / cp300 (checkpoints of j = 0 runs). A level's count is the smallest tested count at
which every instance has a run within the cap and the on-time total reaches the target.
Pricing at K*: per instance one run (any j, any count <= K*, within the cap), minimising the sum of
per-transporter crew hours subject to the on-time total >= target (dynamic programme).

  python analyse_study.py <study> [out_prefix]
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STUDY_ROOT = ROOT / 'fleet_sizing'
SEEDS = list(range(101, 131))


def load(study, spec):
    runs = {}
    d = study / 'runs' / spec['name']
    if d.exists():
        for p in d.glob('*.json'):
            r = json.loads(p.read_text(encoding='utf8'))
            j = r['job']
            if r['status'] != 'OK':
                runs[j['K'], j['seed'], j['j']] = None
                continue
            runs[j['K'], j['seed'], j['j']] = dict(
                on=r['on_time'], over=r['n_over'], crew_veh=r['crew_veh_h'], crew_team=r['crew_team_h'],
                after=r['after_h'], coop=r['n_coop'], wall=r['wall_s'], tl=r['time_limit_reached'],
                cps={c['it']: (c['on_time'], c.get('n_over', 0), c['crew_s'] / 3600, c['wall']) for c in r['checkpoints']})
    return runs


def options(runs, K, s, level):
    out = []
    for (k, ss, j), v in runs.items():
        if ss != s or k > K or v is None:
            continue
        if level == 'final':
            if v['over'] == 0:
                out.append((v['on'], v['crew_veh'], v['crew_team'], v['after'], v['coop'], (k, ss, j)))
        elif level == 'single':
            if j == 0 and v['over'] == 0:
                out.append((v['on'], v['crew_veh'], v['crew_team'], v['after'], v['coop'], (k, ss, j)))
        else:
            it = int(level[2:])
            if j == 0 and it in v['cps'] and v['cps'][it][1] == 0:
                out.append((v['cps'][it][0], v['cps'][it][2], None, None, None, (k, ss, j)))
    return out


def qualifies(runs, K, level, need, seeds=SEEDS):
    tot = 0
    for s in seeds:
        o = options(runs, K, s, level)
        if not o:
            return False
        tot += max(x[0] for x in o)
    return tot >= need


def knapsack(runs, K, need, seeds=SEEDS):
    """min sum crew_veh s.t. sum on >= need; returns chosen tuples per seed."""
    INF = float('inf')
    dp = {0: (0.0, [])}
    for s in seeds:
        o = options(runs, K, s, 'final')
        # keep the Pareto set (more on-time, less crew)
        o.sort(key=lambda x: (-x[0], x[1]))
        par, best = [], INF
        for x in o:
            if x[1] < best:
                par.append(x)
                best = x[1]
        nd = {}
        for t, (c, ch) in dp.items():
            for x in par:
                t2 = min(need, t + x[0])
                c2 = c + x[1]
                if c2 < nd.get(t2, (INF,))[0]:
                    nd[t2] = (c2, ch + [x])
        dp = nd
    return dp.get(need, (None, None))[1]


def analyse(study):
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    gp = STUDY_ROOT / 'results' / 'greedy_level.json'
    greedy = json.loads(gp.read_text(encoding='utf8')) if study.name == 'main' and gp.exists() else {}
    rows = []
    for sp in specs:
        seeds = sp.get('seeds', SEEDS)
        ntot = sp.get('n_total', 97 * len(seeds))
        need = math.ceil(0.95 * ntot - 1e-9)
        runs = load(study, sp)
        tested = sorted({k for (k, s, j) in runs})
        complete = [k for k in tested if all((k, s, 0) in runs for s in seeds)]
        row = dict(series=sp['name'], cell=sp['cell'], family=sp['family'], K_start=sp['K_start'], tested=complete)
        for lev in ('final', 'single', 'cp0', 'cp100', 'cp300'):
            q = [k for k in complete if qualifies(runs, k, lev, need, seeds)]
            row['K_' + lev] = min(q) if q else None
        k = row['K_final']
        if sp['name'] in greedy:
            row['K_greedy'] = greedy[sp['name']]['K_greedy']
        row['boundary_checked'] = k is not None and (k - 1 < sp['K_min'] or all((k - 1, s, j) in runs for s in seeds for j in (1, 2)))
        if k is not None:
            ch = knapsack(runs, k, need, seeds)
            n = len(seeds)
            row.update(on_time=sum(x[0] for x in ch) / ntot, crew_veh_h=sum(x[1] for x in ch) / n,
                       crew_team_h=sum(x[2] for x in ch) / n, after_h=sum(x[3] for x in ch) / n,
                       after_days=sum(x[3] > 0 for x in ch), coop_share=sum(x[4] for x in ch) / ntot,
                       shift_h=64 * k)
        row['runs'] = len(runs)
        row['time_limit_hits'] = sum(1 for v in runs.values() if v and v['tl'])
        row['wall_h'] = sum(v['wall'] for v in runs.values() if v) / 3600
        rows.append(row)
    return rows


if __name__ == '__main__':
    study = STUDY_ROOT / sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
    rows = analyse(study)
    out = STUDY_ROOT / 'results' / ('%s_fleets.csv' % prefix)
    keys = ['series', 'cell', 'family', 'K_start', 'K_final', 'K_single', 'K_cp0', 'K_cp100', 'K_cp300', 'K_greedy',
            'boundary_checked',
            'on_time', 'crew_veh_h', 'crew_team_h', 'after_h', 'after_days', 'coop_share', 'shift_h', 'runs',
            'time_limit_hits', 'wall_h']
    with out.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    done = [r for r in rows if r['K_final'] is not None and r['boundary_checked']]
    print(json.dumps(dict(series=len(rows), finished=len(done), runs=sum(r['runs'] for r in rows),
                          time_limit_hits=sum(r['time_limit_hits'] for r in rows))))
