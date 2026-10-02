"""Strength of the main-case decisions: day-instance bootstrap, grading of the search-dependent decisions, ranks
under handling variability, and the summary numbers of the main claim.
Uses only stored runs and replays of the main study.

  python decision_strength.py [workers]   -> results/bootstrap_series.csv, bootstrap_decisions.csv, grading_series.csv, grading_decisions.csv,
                                        handling_ranks.csv, claim_numbers.json, R25_strength_summary.md
  python decision_strength.py bound        -> results/search_bound.json (search_bound)
  python decision_strength.py selfcheck
"""
import csv
import json
import math
import statistics as st
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
STUDY = STUDY_ROOT / 'main'
sys.path.insert(0, str(HERE))
import cost_decisions as C                                     # noqa: E402

SEEDS = list(range(101, 131))
NEED = 2765
B, RNG_SEED = 2000, 20260930
LABS = ('shift_h', 'shift_ot_h')


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


# ---------------------------------------------------------------- compact run table (cached)
def _compact_series(sp):
    import analyse_study as A
    runs = A.load(STUDY, sp)
    return [dict(series=sp['name'], K=k, seed=s, j=j, on=v['on'], over=v['over'], after_h=v['after'], crew_veh_h=v['crew_veh'], coop=v['coop'])
            for (k, s, j), v in runs.items() if v is not None]


def compact(workers):
    p = RES / 'main_runs_compact.csv'
    if not p.exists() or 'coop' not in open(p, encoding='utf-8-sig').readline():      # older tables lack the coop column
        specs = json.loads((STUDY / 'series.json').read_text(encoding='utf8'))
        with ProcessPoolExecutor(workers) as ex:
            rows = [r for part in ex.map(_compact_series, specs) for r in part]
        with open(p, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    runs = defaultdict(dict)
    for r in rcsv(p):
        runs[r['series']][int(r['K']), int(r['seed']), int(r['j'])] = (int(r['on']), int(r['over']), float(r['after_h']), int(r['coop']))
    return runs


def best_table(runs, js=(0, 1, 2)):
    """(K, s) -> (on, after_h, coupled blocks) of the best option at counts <= K (any listed j, within the cap); ties: smaller after_h,
    then (count, j) ascending. K over the complete tested counts."""
    tested = sorted(k for k in {k for (k, s, j) in runs} if all((k, s, 0) in runs for s in SEEDS))
    out = {}
    for K in tested:
        for s in SEEDS:
            opts = [(-on, after, k, j, co) for (k, ss, j), (on, over, after, co) in runs.items() if ss == s and k <= K and j in js and over == 0]
            if opts:
                b = min(opts)
                out[K, s] = (-b[0], b[1], b[4])
    return tested, out


# ---------------------------------------------------------------- day-instance bootstrap
def bootstrap(runs_all, fleets, specs):
    rng = np.random.default_rng(RNG_SEED)
    draws = np.stack([np.bincount(rng.integers(0, 30, 30), minlength=30) for _ in range(B)])
    draws = np.vstack([np.ones(30, dtype=int), draws])                 # row 0: the original sample
    kb, ab, cb, ser_rows = {}, {}, {}, []
    for sp in specs:
        name = sp['name']
        tested, bt = best_table(runs_all[name])
        K_b = np.full(B + 1, -1)
        A_b = np.zeros(B + 1)
        C_b = np.zeros(B + 1)                                          # coupled share at K*_b
        flag = np.zeros(B + 1, dtype=int)                              # 0 inside, -1 lower, +1 upper truncation
        for K in tested:
            ok = np.array([(K, s) in bt for s in SEEDS])
            on = np.array([bt.get((K, s), (0, 0.0, 0))[0] for s in SEEDS])
            af = np.array([bt.get((K, s), (0, 0.0, 0))[1] for s in SEEDS])
            co = np.array([bt.get((K, s), (0, 0.0, 0))[2] for s in SEEDS])
            feas = (draws[:, ~ok].sum(axis=1) == 0) & (draws @ on >= NEED)
            new = feas & (K_b < 0)
            K_b[new] = K
            A_b[new] = (draws[new] @ af) / 30.0
            C_b[new] = (draws[new] @ co) / (97.0 * 30)
            if K == tested[0]:
                flag[new] = -1
        miss = K_b < 0
        Kmax = tested[-1]
        af = np.array([bt.get((Kmax, s), (0, 0.0, 0))[1] for s in SEEDS])
        co = np.array([bt.get((Kmax, s), (0, 0.0, 0))[2] for s in SEEDS])
        K_b[miss] = Kmax + 1
        A_b[miss] = (draws[miss] @ af) / 30.0
        C_b[miss] = (draws[miss] @ co) / (97.0 * 30)
        flag[miss] = 1
        kf = int(fleets[name]['K_final'])
        assert K_b[0] == kf, (name, K_b[0], kf)
        kb[name], ab[name], cb[name] = K_b, A_b, C_b
        c = Counter(K_b[1:].tolist())
        ser_rows.append(dict(series=name, cell=sp['cell'], family=sp['family'], K_star=kf, P_same=c[kf] / B,
                             P_lower=sum(v for k, v in c.items() if k < kf) / B, P_higher=sum(v for k, v in c.items() if k > kf) / B,
                             lower_trunc=int((flag[1:] == -1).sum()), upper_trunc=int((flag[1:] == 1).sum()),
                             dist=' '.join('%d:%d' % (k, v) for k, v in sorted(c.items()))))
    # decisions
    main = rcsv(RES / 'main_decisions.csv')
    ref = {(x['cell'], x['model'], round(float(x['r']), 6), x['labour']): x['winner'] for x in main if x['labour'] in LABS}
    rs = C.main_r()
    by_cell = defaultdict(list)
    for sp in specs:
        by_cell[sp['cell']].append(sp)
    dec_rows, b0_diff = [], Counter()
    for m in C.MAIN_MODELS:
        P = C.proxy(m)
        for cell, sps in sorted(by_cell.items()):
            fams = [sp['family'] for sp in sps]
            rows_cap = []
            for sp in sps:
                memo = {int(k): P(C.caps(cell, sp['family'], int(k))) for k in set(kb[sp['name']].tolist())}
                rows_cap.append(np.vectorize(memo.get)(kb[sp['name']]))
            cap = np.stack(rows_cap)                                       # F x (B+1)
            Km = np.stack([kb[sp['name']] for sp in sps]).astype(float)
            Am = np.stack([ab[sp['name']] for sp in sps])
            Cm = np.stack([cb[sp['name']] for sp in sps])
            for r in rs:
                for lab in LABS:
                    lab_cost = 64 * Km + (C.OT * C.OMEGA * Am if lab == 'shift_ot_h' else 0)
                    cost = r * cap + lab_cost
                    best = cost.min(axis=0)
                    w = ref[cell, C.mname(m), round(r, 6), lab]
                    wi = fams.index(w)
                    win = np.isclose(cost[wi], best, rtol=0, atol=1e-9)
                    if not win[0]:
                        b0_diff[lab] += 1
                    wb = cost.argmin(axis=0)                                  # winner of each resample (claim support)
                    cw = Cm[wb, np.arange(cost.shape[1])]
                    dec_rows.append(dict(cell=cell, model=C.mname(m), r=r, labour=lab, winner=w, support=float(win[1:].mean()),
                                         b0_same=bool(win[0]), claim_support=float((cw[1:] <= 0.10 + 1e-12).mean())))
    assert b0_diff['shift_h'] == 0, b0_diff
    return ser_rows, dec_rows, b0_diff


# ---------------------------------------------------------------- grading of search-dependent decisions
def grading(runs_all, fleets, specs):
    rows, deltas, recovered = [], [], 0
    for sp in specs:
        name, fam = sp['name'], sp['family']
        kf = int(fleets[name]['K_final'])
        kb = kf - 1
        if kb < C.floor_of(fam):
            continue
        runs = runs_all[name]
        if not any(k <= kb for (k, ss, j) in runs):     # K*-1 never run (two-round cap, liu_massdep_tight_200): not graded
            rows.append(dict(series=name, cell=sp['cell'], family=fam, K_star=kf, ON=None, g=None, c=None, delta=None,
                             ON_corr=None, g_corr=None, grade='untested'))
            continue
        on3, on0, c, on3c = 0, 0, 0, 0
        d = 0
        for s in SEEDS:
            o3 = [on for (k, ss, j), (on, over, a, co) in runs.items() if ss == s and k <= kb and over == 0]
            o0 = [on for (k, ss, j), (on, over, a, co) in runs.items() if ss == s and k <= kb and over == 0 and j == 0]
            if not o3:                              # the best over-cap run fills the gap
                c += 1
                oa = [on for (k, ss, j), (on, over, a, co) in runs.items() if ss == s and k <= kb]
                assert oa, (name, s)
                on3c += max(oa)
                continue
            on3 += max(o3)
            on3c += max(o3)
            if o0:
                d += max(o3) - max(o0)
            else:
                recovered += 1
        deltas.append(d)
        rows.append(dict(series=name, cell=sp['cell'], family=fam, K_star=kf, ON=on3, g=NEED - on3, c=c, delta=d,
                         ON_corr=on3c, g_corr=NEED - on3c))
    dmax = max(deltas)
    d95 = float(np.percentile(deltas, 95))
    for r in rows:
        if r.get('grade') == 'untested':
            continue
        r['grade'] = 'strong' if r['g_corr'] > dmax else ('medium' if r['g_corr'] > d95 else 'weak')
    grade = {(r['cell'], r['family']): r['grade'] for r in rows}
    order = {'weak': 0, 'medium': 1, 'strong': 2}
    dec = []
    for x in rcsv(RES / 'main_decisions.csv'):
        if x['status'] != 'search-dependent':
            continue
        gs = [grade[x['cell'], f] for f in x['flip_by'].split() if grade[x['cell'], f] != 'untested']
        assert gs, x
        dec.append(dict(cell=x['cell'], model=x['model'], r=float(x['r']), labour=x['labour'], winner=x['winner'],
                        flip_by=x['flip_by'], grade=min(gs, key=order.get)))
    return rows, dec, dict(delta_max=dmax, delta_95=d95, n_series=len(rows), recovered_instances=recovered)


# ---------------------------------------------------------------- ranks under handling variability
def handling_ranks(fleets):
    rep = json.loads((RES / 'main_replay.json').read_text(encoding='utf8'))
    main = rcsv(RES / 'main_decisions.csv')
    rows = []
    for x in main:
        if x['model'] != 'affine' or x['labour'] != 'shift_h':
            continue
        fams = {f: v for f, v in ((r['family'], rep[r['series']]) for r in fleets.values() if r['cell'] == x['cell'])}
        order = sorted(fams, key=lambda f: -fams[f]['replay_on_pert'])
        w = x['winner']
        rows.append(dict(cell=x['cell'], r=float(x['r']), winner=w, rank=order.index(w) + 1, n_types=len(order),
                         winner_pert=fams[w]['replay_on_pert'], best_type=order[0], best_pert=fams[order[0]]['replay_on_pert'],
                         gap_pp=100 * (fams[order[0]]['replay_on_pert'] - fams[w]['replay_on_pert'])))
    return rows


# ---------------------------------------------------------------- main-claim numbers and mechanism
def _mechanism(sp):
    import schedule_replay as RP
    for sub in ('common', 'search'):
        p = str(RP.SOLVER / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    from core import evaluate
    K, need, ntot, keys = RP.chosen(STUDY, sp)
    sync = work = svc = svc_coop = 0.0
    for k, s, j in keys:
        r = json.loads((STUDY / 'runs' / sp['name'] / ('K%d_s%d_j%d.json' % (k, s, j))).read_text(encoding='utf8'))
        team = {int(i): tuple(v) for i, v in r['team'].items()}
        inst = RP.instance(STUDY, sp, k, s)
        ev = evaluate(inst, r['order'], team, 0)
        sync += ev['sync']
        work += ev['work']
        svc += ev['service']
        svc_coop += sum(len(S) * (inst.D[i] + inst.dl[i]) for i, S in team.items() if len(S) > 1)
    return sp['name'], dict(sync_share=sync / work, coop_service_share=svc_coop / svc)


def claim_numbers(fleets, specs, workers):
    main = rcsv(RES / 'main_decisions.csv')
    coop = {(r['cell'], r['family']): float(r['coop_share']) for r in fleets.values()}
    w = [(x['cell'], x['winner']) for x in main]
    n = len(w)
    light = {'200', '250', '270', '300', '325'}
    out = dict(decisions=n, winner_coop_le_10pct=sum(coop[k] <= 0.10 for k in w) / n, winner_coop_zero=sum(coop[k] == 0 for k in w) / n,
               winner_light_homogeneous=sum(f in light for _, f in w) / n, winner_mix=sum(f.startswith('MX') for _, f in w) / n,
               by_labour={lab: dict(coop_le_10pct=sum(coop[x['cell'], x['winner']] <= 0.10 for x in main if x['labour'] == lab) /
                                    sum(x['labour'] == lab for x in main)) for lab in C.LAB4})
    cmax = {}
    for x in main:                                   # largest winner coupled share per condition, 180 settings
        cmax[x['cell']] = max(cmax.get(x['cell'], 0.0), coop[x['cell'], x['winner']])
    out['conditions_all_le_10pct'] = sum(v <= 0.10 for v in cmax.values())
    out['condition_exceptions'] = {c: round(v, 4) for c, v in sorted(cmax.items()) if v > 0.10}
    if (STUDY / 'runs').exists():
        with ProcessPoolExecutor(workers) as ex:
            mech = dict(ex.map(_mechanism, specs))
    else:                           # public release: the main-yard schedules are not released; keep the stored values
        mech = json.loads((RES / 'claim_numbers.json').read_text(encoding='utf8'))['per_series']
    winners = {(x['cell'], x['winner']) for x in main}
    wname = {'%s_%s' % k for k in winners}
    for key, sel in (('all_series', lambda s: True), ('winning_series', lambda s: s in wname)):
        v = [m for s, m in mech.items() if sel(s)]
        out['mechanism_' + key] = dict(n=len(v), **{f: dict(median=st.median(m[f] for m in v), min=min(m[f] for m in v), max=max(m[f] for m in v))
                                                   for f in ('sync_share', 'coop_service_share')})
    return out, mech


def main(workers=6):
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    specs = json.loads((STUDY / 'series.json').read_text(encoding='utf8'))
    fleets = {r['series']: r for r in rcsv(RES / 'main_fleets.csv')}
    runs_all = compact(workers)
    L = ['# Strength of the main-case decisions', '']
    ser, dec, b0 = bootstrap(runs_all, fleets, specs)
    write(RES / 'bootstrap_series.csv', ser)
    write(RES / 'bootstrap_decisions.csv', dec)
    L += ['## Day-instance bootstrap (B = 2,000, seed 20260930, common random numbers)', '',
          '- the original sample reproduces the 384 K* of the main study and all winners under the shift measure; '
          'under the shift-plus-overtime measure, which selects options differently, decisions that differ from the '
          'main study on the original sample: %d / 1,620.' % b0['shift_ot_h'],
          '- series: P(K*_b = K*) median %.2f; series with lower truncation %d, with upper truncation %d.' % (
              st.median(x['P_same'] for x in ser), sum(x['lower_trunc'] > 0 for x in ser), sum(x['upper_trunc'] > 0 for x in ser)), '',
          '| labour measure | decisions | support ≥ 95% | 80–95% | < 80% | median support |',
          '| --- | --- | --- | --- | --- | --- |']
    for lab in LABS:
        g = [x['support'] for x in dec if x['labour'] == lab]
        L.append('| %s | %d | %d | %d | %d | %.3f |' % (lab, len(g), sum(v >= 0.95 for v in g), sum(0.8 <= v < 0.95 for v in g),
                                                   sum(v < 0.8 for v in g), st.median(g)))
    L += ['', '**Main-claim support**: share of resamples whose winner has a coupled share ≤ 10%.', '',
          '| labour measure | share of (setting, resample) pairs that satisfy it | settings satisfied in ≥ 95% of '
          'resamples | settings satisfied in ≥ 80% of resamples |', '| --- | --- | --- | --- |']
    for lab in LABS:
        g = [x['claim_support'] for x in dec if x['labour'] == lab]
        L.append('| %s | %.1f%% | %d / %d | %d / %d |' % (lab, 100 * st.mean(g), sum(v >= 0.95 for v in g), len(g), sum(v >= 0.8 for v in g), len(g)))
    cells = sorted({x['cell'] for x in dec})
    L += ['', 'decisions with support below 80% per condition (shift measure, 45 decisions each): ' + ', '.join(
        '%s %d' % (c, sum(1 for x in dec if x['cell'] == c and x['labour'] == 'shift_h' and x['support'] < 0.8)) for c in cells), '']
    ser2, dec2, sc = grading(runs_all, fleets, specs)
    write(RES / 'grading_series.csv', ser2)
    write(RES / 'grading_decisions.csv', dec2)
    L += ['## Grading of the search-dependent decisions', '',
          '- scale: at K* − 1 of %d series, total extra on-time blocks of "best of three" over "single run j = 0": '
          'Δmax = %d, Δ95 = %.1f; instances where j = 0 has no schedule within the cap but j = 1 or 2 has: %d.' % (
              sc['n_series'], sc['delta_max'], sc['delta_95'], sc['recovered_instances']),
          '- grades use the gap g′ (instances without a capped schedule are filled with the best on-time count of '
          'an over-cap run); series with c > 0: %d, reported separately and not graded.'
          % sum((r['c'] or 0) > 0 for r in ser2),
          '- series grades: strong %d, medium %d, weak %d; not graded because K* − 1 was not run: %d.' % tuple(sum(r['grade'] == g for r in ser2) for g in ('strong', 'medium', 'weak', 'untested')), '',
          '| labour measure | search-dependent decisions | strong | medium | weak |', '| --- | --- | --- | --- | --- |']
    for lab in C.LAB4:
        g = [x['grade'] for x in dec2 if x['labour'] == lab]
        L.append('| %s | %d | %d | %d | %d |' % (lab, len(g), g.count('strong'), g.count('medium'), g.count('weak')))
    g = [x['grade'] for x in dec2]
    L += ['| total | %d | %d | %d | %d |' % (len(g), g.count('strong'), g.count('medium'), g.count('weak')), '']
    er = handling_ranks(fleets)
    write(RES / 'handling_ranks.csv', er)
    rm = C.main_r()[4]
    mid = [x for x in er if abs(x['r'] - rm) < 1e-9]
    L += ['## Ranks under handling variability (affine price, shift labour; 1 = highest perturbed on-time rate)', '',
          '- all (condition, r): median rank of the winner %s; rank ≥ 9: %d / %d.' % (st.median(x['rank'] for x in er), sum(x['rank'] >= 9 for x in er), len(er)),
          '- at r = %.1f: conditions where the winner ranks ≥ 9: %d / 36; in these, median shortfall of the winner '
          'behind the most robust type %.1f percentage points; conditions where the winner ranks first: %s.' % (
              rm, sum(x['rank'] >= 9 for x in mid), st.median([x['gap_pp'] for x in mid if x['rank'] >= 9] or [0]),
              ', '.join(x['cell'] for x in mid if x['rank'] == 1)),
          '- at r = %.1f, gap between the winner and the most robust type over all 36 conditions (percentage '
          'points): median %.1f.' % (rm, st.median(x['gap_pp'] for x in mid)), '']
    claim, mech = claim_numbers(fleets, specs, workers)
    (RES / 'claim_numbers.json').write_text(json.dumps(dict(claim, per_series=mech), indent=1) + '\n', encoding='utf8')
    ma, mw = claim['mechanism_all_series'], claim['mechanism_winning_series']
    L += ['## Main-claim numbers (main grid, 6,480 decisions)', '',
          '- winner coupled share on its pricing-selected schedules at K* ≤ 10%%: %.1f%%; zero: %.1f%%; winner a '
          'homogeneous fleet of ≤ 325 t: %.1f%%; an `MX` mix: %.1f%%.' % (
              100 * claim['winner_coop_le_10pct'], 100 * claim['winner_coop_zero'], 100 * claim['winner_light_homogeneous'], 100 * claim['winner_mix']),
          '- share with a winner coupled share ≤ 10%%, by labour measure: %s.' % ', '.join('%s %.1f%%' % (k, 100 * v['coop_le_10pct']) for k, v in claim['by_labour'].items()),
          '- by condition: in %d / 36 conditions the winner coupled share is ≤ 10%% in all 180 settings; '
          'exceptions: %s.' % (
              claim['conditions_all_le_10pct'], ', '.join('%s %.1f%%' % (c, 100 * v) for c, v in claim['condition_exceptions'].items())),
          '- mechanism (replay of the pricing-selected schedules at K*): synchronisation waiting as a share of '
          'transporter working time, all series median %.2f%% (max %.2f%%), winning series median %.2f%% '
          '(max %.2f%%); coupled work as a share of transporter service time, all series median %.1f%%, winning '
          'series median %.1f%%.' % (
              100 * ma['sync_share']['median'], 100 * ma['sync_share']['max'], 100 * mw['sync_share']['median'], 100 * mw['sync_share']['max'],
              100 * ma['coop_service_share']['median'], 100 * mw['coop_service_share']['median'])]
    (RES / 'R25_strength_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def search_bound():
    """How far could search-dependent counts move the coupled share of the cheapest fleet? Fleets that couple more than
    one block in ten lose one transporter (not below the family floor) and are repriced as in the search-dependence rule
    (cost_decisions.decisions: shift labour at the lower count, operating labour unchanged): (a) only those graded weak or
    medium, (b) all of them. Share of the 6,480 settings whose cheapest fleet couples at most one block in ten, overall
    and outside the extra-heavy scenario; share of weak or medium grades per family.  -> results/search_bound.json"""
    fleets = rcsv(RES / 'main_fleets.csv')
    coop = {(r['cell'], r['family']): float(r['coop_share']) for r in fleets}
    grade = {(r['cell'], r['family']): r['grade'] for r in rcsv(RES / 'grading_series.csv')}
    fl = C.load(RES / 'main_fleets.csv')
    weak = lambda k: grade.get(k) in ('weak', 'medium')

    def shares(cut):
        f2 = {k: (dict(v, K=v['K'] - 1) if cut(k) and coop[k] > 0.10 and v['K'] - 1 >= C.floor_of(k[1]) else v) for k, v in fl.items()}
        rows = C.decisions(f2, C.MAIN_MODELS, C.main_r(), C.LAB4)
        ok = [coop[x['cell'], x['winner']] <= 0.10 for x in rows]
        out = [x for x, o in zip(rows, ok) if not x['cell'].startswith('extraheavy')]
        return dict(settings=len(rows), share=sum(ok) / len(rows), lowered=sum(f2[k]['K'] < fl[k]['K'] for k in fl),
                    share_outside_extra_heavy=sum(coop[x['cell'], x['winner']] <= 0.10 for x in out) / len(out))
    fams = sorted({f for _, f in fl}, key=lambda f: (f.startswith('MX'), f))
    res = dict(reported=shares(lambda k: False), weak_or_medium_minus_one=shares(weak), all_minus_one=shares(lambda k: True),
               weak_or_medium_by_family={f: dict(series=sum(1 for k in fl if k[1] == f), weak_or_medium=sum(1 for k in fl if k[1] == f and weak(k)))
                                         for f in fams})
    (RES / 'search_bound.json').write_text(json.dumps(res, indent=1) + '\n', encoding='utf8')
    print(json.dumps(res, indent=1))


def write(path, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def selfcheck():
    """best_table tie rule and the bootstrap feasibility rule on a synthetic two-seed series."""
    global SEEDS, NEED
    SEEDS, NEED = [1, 2], 180
    runs = {(3, 1, 0): (90, 0, 1.0, 5), (3, 2, 0): (80, 0, 0.5, 0), (4, 1, 0): (95, 0, 2.0, 1), (4, 2, 0): (80, 1, 0.0, 0),
            (4, 2, 1): (88, 0, 0.2, 2), (3, 1, 1): (90, 0, 0.3, 4)}
    tested, bt = best_table(runs)
    assert tested == [3, 4] and bt[3, 1] == (90, 0.3, 4) and bt[4, 2] == (88, 0.2, 2) and bt[4, 1] == (95, 2.0, 1), bt
    # K=3: 90 + 80 = 170 < 180; K=4: 95 + 88 = 183 >= 180
    assert not (bt[3, 1][0] + bt[3, 2][0] >= NEED) and bt[4, 1][0] + bt[4, 2][0] >= NEED
    print('decision_strength self-check passed')


if __name__ == '__main__':
    if sys.argv[1:2] == ['selfcheck']:
        selfcheck()
    elif sys.argv[1:2] == ['bound']:
        search_bound()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
