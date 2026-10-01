"""Robust sizing (directory `robust`).

Conditions with the Jiang, Roh-Cha and Liu mass scenarios x short and mass-dependent handling x baseline due dates,
11 reference families (66 series). New j = 0 runs at K*+1 and K*+2 (30 instances; solver, budget and cap objective
of the main study; seeds s + 300000 + 1000 j), study directory `fleet_sizing/robust`.
Replay: at K*, K*+1, K*+2 (and K*+3 when needed) each instance's best capped schedule among the runs of the main
study and of this study with count <= K (most on-time; ties: smaller maximum delay, then (count, source, j)) is
replayed in the 20 handling-variability scenarios (loading and unloading x U(0.5, 1.5), random numbers from
(instance seed, scenario), as schedule_replay). K_rob = smallest count with perturbed mean on-time >= 95%; "> K*+3" is
priced at K*+4. Pricing: main grid, shift and shift + after-shift.

  pypy robust_sizing.py run <phase: 1|2> <workers>     # phase 1: K*+1, K*+2; phase 2: K*+3 for series listed by analyse
  python robust_sizing.py analyse                        # -> results/robust_series.csv, robust_decisions.csv, robust_summary.md, robust/phase2.json
  python robust_sizing.py selfcheck
"""
import csv
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
MAIN_DIR = STUDY_ROOT / 'main'
ROBUST_DIR = STUDY_ROOT / 'robust'
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(HERE))
import fleet_scan                                              # noqa: E402

CELLS = ['%s_%s_baseline' % (m, h) for m in ('jiang', 'rohcha', 'liu') for h in ('short', 'massdep')]
SEEDS = list(range(101, 131))
OFFSET = 300000
N_SCEN, SPREAD, NEED_RATE = 20, 0.5, 0.95


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def specs():
    kf = {r['series']: int(r['K_final']) for r in rcsv(RES / 'main_fleets.csv')}
    out = [dict(sp, K_star=kf[sp['name']]) for sp in json.loads((MAIN_DIR / 'series.json').read_text(encoding='utf8')) if sp['cell'] in CELLS]
    assert len(out) == 66, len(out)
    return out


def jobs(phase):
    sps = {sp['name']: sp for sp in specs()}
    if phase == 1:
        todo = [(name, sp['K_star'] + d) for name, sp in sps.items() for d in (1, 2)]
    else:
        todo = [(name, sp['K_star'] + 3) for name in json.loads((ROBUST_DIR / 'phase2.json').read_text(encoding='utf8'))
                for sp in (sps[name],)]
    out = []
    for name, K in todo:
        sp = sps[name]
        for s in SEEDS:
            if (ROBUST_DIR / 'runs' / name / ('K%d_s%d_j0.json' % (K, s))).exists():
                continue
            out.append(dict(series=name, K=K, seed=s, j=0, caps=fleet_scan.caps_of(sp['family'], K), base='../main/' + sp['base'][str(s)],
                            objective=sp['objective'], tmax_s=sp['tmax_s'], seed_offset=OFFSET, study=str(ROBUST_DIR)))
    return out


def run(phase, workers):
    import psutil
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing as mp
    p = psutil.Process()
    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    p.cpu_affinity(list(range(1, psutil.cpu_count())))
    js = jobs(phase)
    js.sort(key=lambda j: -j['K'])
    with ProcessPoolExecutor(workers, mp_context=mp.get_context('spawn')) as ex:
        for i, r in enumerate(ex.map(fleet_scan.work, js), 1):
            if i % 50 == 0 or i == len(js):
                (ROBUST_DIR / 'progress.json').write_text(json.dumps(dict(phase=phase, done=i, total=len(js))) + '\n', encoding='utf8')


# ---------------------------------------------------------------- analysis (CPython, `solver_reference` evaluator as schedule_replay)
def candidates(sp, K, s):
    """(on, max_tard, k, source, j, path) of every capped run with count <= K for instance s."""
    out = []
    for src, d in (('main', MAIN_DIR / 'runs' / sp['name']), ('robust', ROBUST_DIR / 'runs' / sp['name'])):
        if not d.exists():
            continue
        for p in d.glob('K*_s%d_j*.json' % s):
            k = int(p.name.split('_')[0][1:])
            if k > K:
                continue
            r = json.loads(p.read_text(encoding='utf8'))
            if r['status'] == 'OK' and r['n_over'] == 0:
                out.append((-r['on_time'], r['max_tard'], k, src, r['job']['j'], p))
    return sorted(out)


def replay_series(sp, Ks):
    import schedule_replay as RP
    for sub in ('common', 'search'):
        q = str(RP.SOLVER / sub)
        if q not in sys.path:
            sys.path.insert(0, q)
    from core import scenario_inst
    res = {}
    for K in Ks:
        nom_on = pert_on = over = n = 0
        after = 0.0
        missing = 0
        for s in SEEDS:
            c = candidates(sp, K, s)
            if not c:
                missing += 1
                continue
            _, _, k, src, j, path = c[0]
            r = json.loads(path.read_text(encoding='utf8'))
            order, team = r['order'], {int(i): tuple(v) for i, v in r['team'].items()}
            inst = RP.instance(MAIN_DIR, sp, k, s)
            m = RP.metrics(inst, order, team, sp['tmax_s'], 16 * 3600)
            assert m['on'] == r['on_time'] and m['over'] == r['n_over'], (sp['name'], k, s, src, j)
            nom_on += m['on']
            after += m['after_s'] / 3600
            n += inst.n
            for q in range(N_SCEN):
                rng = random.Random(s * 1000 + q)
                L = [x * rng.uniform(1 - SPREAD, 1 + SPREAD) for x in inst.load]
                U = [x * rng.uniform(1 - SPREAD, 1 + SPREAD) for x in inst.unload]
                mp_ = RP.metrics(scenario_inst(inst, L, U), order, team, sp['tmax_s'], 16 * 3600)
                pert_on += mp_['on']
                over += mp_['over'] > 0
        res[K] = dict(missing=missing, nominal=nom_on / n if n else None, perturbed=pert_on / (N_SCEN * n) if n else None,
                      share_over=over / (N_SCEN * (30 - missing)) if n else None, after_h=after / 30)
    return res


def analyse():
    import cost_decisions as C
    sps = specs()
    rows, phase2 = [], []
    for sp in sps:
        ks = sp['K_star']
        have3 = (ROBUST_DIR / 'runs' / sp['name']).exists() and any((ROBUST_DIR / 'runs' / sp['name']).glob('K%d_*' % (ks + 3)))
        Ks = [ks, ks + 1, ks + 2] + ([ks + 3] if have3 else [])
        rep = replay_series(sp, Ks)
        ok = [K for K in Ks if rep[K]['missing'] == 0 and rep[K]['perturbed'] >= NEED_RATE]
        k_rob = min(ok) if ok else None
        if k_rob is None and not have3:
            phase2.append(sp['name'])
        rows.append(dict(series=sp['name'], cell=sp['cell'], family=sp['family'], K_star=ks, K_rob=k_rob if k_rob else ('>%d' % (ks + 3) if have3 else None),
                         **{'pert_K%+d' % (K - ks): rep[K]['perturbed'] for K in Ks}, **{'over_K%+d' % (K - ks): rep[K]['share_over'] for K in Ks},
                         after_h_rob=rep[k_rob]['after_h'] if k_rob else rep[Ks[-1]]['after_h']))
    ROBUST_DIR.mkdir(parents=True, exist_ok=True)
    (ROBUST_DIR / 'phase2.json').write_text(json.dumps(phase2) + '\n', encoding='utf8')
    with open(RES / 'robust_series.csv', 'w', encoding='utf-8-sig', newline='') as f:
        keys = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    if phase2:
        print('phase 2 needed for %d series (K*+3): %s' % (len(phase2), phase2))
        return
    # pricing at K_rob ("> K*+3" at K*+4, counted separately)
    fl = {}
    for r in rows:
        k = r['K_rob'] if isinstance(r['K_rob'], int) else r['K_star'] + 4
        fl[r['cell'], r['family']] = dict(K=k, crew_veh_h=0.0, crew_team_h=0.0, after_h=r['after_h_rob'])
    nom = {(x['cell'], x['model'], round(float(x['r']), 6), x['labour']): x['winner'] for x in rcsv(RES / 'main_decisions.csv')
           if x['cell'] in CELLS and x['labour'] in ('shift_h', 'shift_ot_h')}
    dec = []
    for m in C.MAIN_MODELS:
        P = C.proxy(m)
        for cell in CELLS:
            fams = {f: v for (c, f), v in fl.items() if c == cell}
            for r in C.main_r():
                for lab in ('shift_h', 'shift_ot_h'):
                    cost = {f: r * P(C.caps(cell, f, v['K'])) + C.labour(v, lab, v['K']) for f, v in fams.items()}
                    w = min(cost, key=cost.get)
                    dec.append(dict(cell=cell, model=C.mname(m), r=r, labour=lab, winner_rob=w, winner_nominal=nom[cell, C.mname(m), round(r, 6), lab]))
    with open(RES / 'robust_decisions.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(dec[0]))
        w.writeheader()
        w.writerows(dec)
    L = ['# Robust sizing', '',
         '- K_rob - K*: %s' % {d: sum(1 for r in rows if isinstance(r['K_rob'], int) and r['K_rob'] - r['K_star'] == d) for d in range(4)},
         '- above K*+3: %d' % sum(1 for r in rows if not isinstance(r['K_rob'], int))]
    for lab in ('shift_h', 'shift_ot_h'):
        g = [x for x in dec if x['labour'] == lab]
        L.append('- %s: robust choice differs from the nominal choice in %d of %d settings' % (lab, sum(x['winner_rob'] != x['winner_nominal'] for x in g), len(g)))
    (RES / 'robust_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def selfcheck():
    """Series selection, job construction and the K* replay path (main-study runs only, one series, three seeds)."""
    sps = specs()
    assert {sp['cell'] for sp in sps} == set(CELLS) and all(sp['family'] for sp in sps)
    sp = next(x for x in sps if x['name'] == 'liu_short_baseline_425')
    j = [x for x in jobs(1) if x['series'] == sp['name']]
    assert len(j) == 60 and {x['K'] for x in j} == {sp['K_star'] + 1, sp['K_star'] + 2} and all(x['seed_offset'] == OFFSET for x in j)
    assert all((ROBUST_DIR / x['base']).resolve().exists() for x in j[:3])
    global SEEDS
    keep, SEEDS = SEEDS, SEEDS[:3]
    rep = replay_series(sp, [sp['K_star']])
    SEEDS = keep
    assert rep[sp['K_star']]['missing'] == 0 and 0 < rep[sp['K_star']]['perturbed'] <= rep[sp['K_star']]['nominal'] + 0.2
    print('x1 self-check passed:', sp['name'], sp['K_star'], rep)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'run':
        run(int(a[1]), int(a[2]))
    elif a[0] == 'analyse':
        analyse()
    else:
        selfcheck()
