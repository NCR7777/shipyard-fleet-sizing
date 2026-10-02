"""Robust sizing (directory `robust`).

Conditions with the Jiang, Roh-Cha and Liu mass scenarios x short and mass-dependent handling x baseline due dates,
11 reference families (66 series). New j = 0 runs at K*+1 and K*+2 (30 instances; solver, budget and cap objective
of the main study; seeds s + 300000 + 1000 j), study directory `fleet_sizing/robust`.
Replay: at K*, K*+1, K*+2 (and K*+3 when needed), for each instance, every stored capped schedule (runs of the main
study and of this study) with count <= K is replayed in 20 selection scenarios and the one with the highest
perturbed on-time is kept (ties: more nominal on-time, smaller count, then source and j); the kept schedule is
evaluated in the 20 handling-variability scenarios (loading and unloading x U(0.5, 1.5), random numbers from
(instance seed, scenario), as schedule_replay). Selection scenarios draw from (instance seed, SEL_OFFSET + scenario),
disjoint from the evaluation streams. K_rob = smallest count with perturbed mean on-time >= 95%. Pricing: main grid,
shift and shift + after-shift, at K_rob. A series without K_rob up to K*+3 is not priced; a setting is decided only
if each such fleet, priced at K*+4 with shift labour 64 per transporter and no after-shift work, still costs at least
as much as the robust winner; otherwise the setting is reported as unresolved.
  pypy robust_sizing.py run <phase: 1|2> <workers>     # phase 1: K*+1, K*+2; phase 2: K*+3 for series listed by analyse
  python robust_sizing.py analyse                        # -> results/robust_series.csv, robust_decisions.csv, robust_summary.md, robust/phase2.json
  python robust_sizing.py selfcheck
"""
import csv
import json
import math
import random
import sys
from collections import Counter
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
SEL_OFFSET = 500                 # selection scenarios: random.Random(s * 1000 + SEL_OFFSET + q), q < N_SCEN


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


def _perturbed(RP, scenario_inst, inst, order, team, tmax, s, offset):
    on = over = 0
    for q in range(N_SCEN):
        rng = random.Random(s * 1000 + offset + q)
        L = [x * rng.uniform(1 - SPREAD, 1 + SPREAD) for x in inst.load]
        U = [x * rng.uniform(1 - SPREAD, 1 + SPREAD) for x in inst.unload]
        m = RP.metrics(scenario_inst(inst, L, U), order, team, tmax, 16 * 3600)
        on += m['on']
        over += m['over'] > 0
    return on, over


def replay_series(sp, Ks):
    import schedule_replay as RP
    for sub in ('common', 'search'):
        q = str(RP.SOLVER / sub)
        if q not in sys.path:
            sys.path.insert(0, q)
    from core import scenario_inst
    acc = {K: dict(nom=0, pert=0, over=0, n=0, after=0.0, missing=0, extra=0) for K in Ks}
    for s in SEEDS:
        scored = []
        for neg_on, _, k, src, j, path in candidates(sp, max(Ks), s):
            r = json.loads(path.read_text(encoding='utf8'))
            order, team = r['order'], {int(i): tuple(v) for i, v in r['team'].items()}
            inst = RP.instance(MAIN_DIR, sp, k, s)
            m = RP.metrics(inst, order, team, sp['tmax_s'], 16 * 3600)
            assert m['on'] == r['on_time'] and m['over'] == r['n_over'], (sp['name'], k, s, src, j)
            sel, _ = _perturbed(RP, scenario_inst, inst, order, team, sp['tmax_s'], s, SEL_OFFSET)
            scored.append(dict(key=(-sel, neg_on, k, src, j), k=k, inst=inst, order=order, team=team, nominal=m))
        evaluated = {}
        for K in Ks:
            pool = [x for x in scored if x['k'] <= K]
            if not pool:
                acc[K]['missing'] += 1
                continue
            best = min(pool, key=lambda x: x['key'])
            if best['key'] not in evaluated:
                evaluated[best['key']] = _perturbed(RP, scenario_inst, best['inst'], best['order'], best['team'], sp['tmax_s'], s, 0)
            on, over = evaluated[best['key']]
            a = acc[K]
            a['nom'] += best['nominal']['on']
            a['pert'] += on
            a['over'] += over
            a['n'] += best['inst'].n
            a['after'] += best['nominal']['after_s'] / 3600
            a['extra'] += best['k'] - sp['K_star']
    res = {}
    for K, a in acc.items():
        n, used = a['n'], 30 - a['missing']
        res[K] = dict(missing=a['missing'], nominal=a['nom'] / n if n else None, perturbed=a['pert'] / (N_SCEN * n) if n else None,
                      share_over=a['over'] / (N_SCEN * used) if used else None, after_h=a['after'] / 30,
                      mean_extra=a['extra'] / used if used else None)
    return res


def _replay_job(args):
    sp, Ks = args
    return sp['name'], replay_series(sp, Ks)


def analyse(workers=8):
    import cost_decisions as C
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing as mp
    sps = specs()
    plan = []
    for sp in sps:
        ks = sp['K_star']
        have3 = (ROBUST_DIR / 'runs' / sp['name']).exists() and any((ROBUST_DIR / 'runs' / sp['name']).glob('K%d_*' % (ks + 3)))
        plan.append((sp, [ks, ks + 1, ks + 2] + ([ks + 3] if have3 else [])))
    with ProcessPoolExecutor(workers, mp_context=mp.get_context('spawn')) as ex:
        reps = dict(ex.map(_replay_job, plan))
    rows, phase2 = [], []
    for sp, Ks in plan:
        ks, rep = sp['K_star'], reps[sp['name']]
        have3 = len(Ks) == 4
        ok = [K for K in Ks if rep[K]['missing'] == 0 and rep[K]['perturbed'] >= NEED_RATE]
        k_rob = min(ok) if ok else None
        if k_rob is None and not have3:
            phase2.append(sp['name'])
        rows.append(dict(series=sp['name'], cell=sp['cell'], family=sp['family'], K_star=ks, K_rob=k_rob if k_rob else ('>%d' % (ks + 3) if have3 else None),
                         **{'pert_K%+d' % (K - ks): rep[K]['perturbed'] for K in Ks}, **{'over_K%+d' % (K - ks): rep[K]['share_over'] for K in Ks},
                         **{'extra_used_K%+d' % (K - ks): rep[K]['mean_extra'] for K in Ks},
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
    # pricing at K_rob; a series without K_rob (K_rob >= K*+4) only bounds the cost from below
    fl, lb = {}, {}
    for r in rows:
        if isinstance(r['K_rob'], int):
            fl[r['cell'], r['family']] = dict(K=r['K_rob'], crew_veh_h=0.0, crew_team_h=0.0, after_h=r['after_h_rob'])
        else:
            lb[r['cell'], r['family']] = r['K_star'] + 4
    nom = {(x['cell'], x['model'], round(float(x['r']), 6), x['labour']): x['winner'] for x in rcsv(RES / 'main_decisions.csv')
           if x['cell'] in CELLS and x['labour'] in ('shift_h', 'shift_ot_h')}
    dec = []
    for m in C.MAIN_MODELS:
        P = C.proxy(m)
        for cell in CELLS:
            fams = {f: v for (c, f), v in fl.items() if c == cell}
            low = {f: k for (c, f), k in lb.items() if c == cell}
            for r in C.main_r():
                for lab in ('shift_h', 'shift_ot_h'):
                    cost = {f: r * P(C.caps(cell, f, v['K'])) + C.labour(v, lab, v['K']) for f, v in fams.items()}
                    w = min(cost, key=cost.get) if cost else ''
                    bound = {f: r * P(C.caps(cell, f, k)) + 64 * k for f, k in low.items()}
                    status = 'decided' if cost and all(b >= cost[w] for b in bound.values()) else 'unresolved'
                    dec.append(dict(cell=cell, model=C.mname(m), r=r, labour=lab, winner_rob=w, status=status,
                                    winner_nominal=nom[cell, C.mname(m), round(r, 6), lab]))
    with open(RES / 'robust_decisions.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(dec[0]))
        w.writeheader()
        w.writerows(dec)
    L = ['# Robust sizing', '',
         '- K_rob - K*: %s' % {d: sum(1 for r in rows if isinstance(r['K_rob'], int) and r['K_rob'] - r['K_star'] == d) for d in range(4)},
         '- no K_rob up to K*+3: %d (%s)' % (sum(1 for r in rows if not isinstance(r['K_rob'], int)),
                                           dict(sorted(Counter(r['cell'] for r in rows if not isinstance(r['K_rob'], int)).items())))]
    for lab in ('shift_h', 'shift_ot_h'):
        g = [x for x in dec if x['labour'] == lab]
        d = [x for x in g if x['status'] == 'decided']
        L.append('- %s: %d of %d settings decided; robust choice differs from the nominal choice in %d of them; by condition: %s'
                 % (lab, len(d), len(g), sum(x['winner_rob'] != x['winner_nominal'] for x in d),
                    dict(sorted(Counter((x['cell'], x['winner_nominal'], x['winner_rob']) for x in d if x['winner_rob'] != x['winner_nominal']).items()))))
    (RES / 'robust_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def selfcheck():
    """Series selection, job construction and the K* replay path (main-study runs only, one series, three seeds)."""
    sps = specs()
    assert {sp['cell'] for sp in sps} == set(CELLS) and all(sp['family'] for sp in sps)
    sp = next(x for x in sps if x['name'] == 'liu_short_baseline_425')
    j = [x for x in jobs(1) if x['series'] == sp['name']]
    assert len(j) in (0, 60) and {x['K'] for x in j} <= {sp['K_star'] + 1, sp['K_star'] + 2} and all(x['seed_offset'] == OFFSET for x in j)
    assert all((ROBUST_DIR / x['base']).resolve().exists() for x in j[:3])          # no jobs left once phase 1 has run
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
