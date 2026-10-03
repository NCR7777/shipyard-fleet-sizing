"""Main-case report from the finished main study: fleet counts, pricing, after-shift labour, pooling, search levels
and the replays.

Inputs: results/main_fleets.csv (analyse_study), R4_decisions_*.csv (cost_decisions), main_replay.json (schedule_replay),
family_pooling.json (family_pooling), greedy_level.json, the decisions and counts of the earlier ten-instance scan, and the base
instances of the main study.

  1. counts vs the counts of the earlier ten-instance scan (K_start); boundary status; smallest count in the
     Liu condition
  2. change of the old-grid winners from the earlier scan to this study (1,620 decisions, 3 labour measures)
  3. search dependence of the decisions on the main grid, by labour measure
  4. after-shift labour pricing (shift vs shift + 1.5 x 4 x after-shift h) and the shift-hard replay: decisions
     (affine, 9 calibrated r, shift labour) re-taken without the types that miss the target when completions
     after 16 h count as late
  5. handling variability of the pricing-selected schedules
  6. counts pooled across fleet families vs own-series counts and the decisions that change (main grid, 3 labour
     measures; the pooled schedules carry no after-shift hours)
  7. search-intensity levels (greedy, construction only, 100, 300, single 786, final = 3 x 786 at K*-1):
     counts, agreement of the winner with the final one on the main grid with shift labour (the levels have
     no schedule-level labour selection, so only the count-driven measure is compared), strata by final
     count (<= 5, 6-10, > 10) and by coupled share (0, (0, 0.3], > 0.3), time per level (checkpoint wall
     time as a share of the full run, and the greedy construction time)
  8. input-only load rule: K_rho = smallest K with the load index rho* averaged over the 30 instances <= 1
     (same rule as paper/code/instances/e3_report.rho_rule_K, which averaged over 10), error d = K* - K_rho by due date

  python report_main.py        -> results/main_summary.md, main_search_levels.csv, main_load_rule.csv
"""
import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
ROOT = STUDY_ROOT.parent
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(HERE))
import cost_decisions as C                                      # noqa: E402

LEVELS = ('greedy', 'cp0', 'cp100', 'cp300', 'single', 'final')


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def ival(x):
    return None if x in (None, '', 'None') else int(float(x))


def fleets_at(rows, level, extra=None):
    out = {}
    for r in rows:
        k = ival(r['K_' + level])
        if k is not None:
            out[r['cell'], r['family']] = dict(K=k, crew_veh_h=float(r['crew_veh_h'] or 0), crew_team_h=float(r['crew_team_h'] or 0),
                                               after_h=float(r['after_h'] or 0), **(extra or {}))
    return out


def winners(fl, models, rs, labs, cells=None):
    """(cell, model, r, labour) -> cheapest family (same costs as cost_decisions.decisions); None if the cell has none."""
    out = {}
    cells = cells or sorted({c for c, _ in fl})
    for m in models:
        P = C.proxy(m)
        for cell in cells:
            fams = {f: v for (c, f), v in fl.items() if c == cell}
            cap = {f: P(C.caps(cell, f, v['K'])) for f, v in fams.items()}
            for r in rs:
                for lab in labs:
                    cost = {f: r * cap[f] + C.labour(v, lab, v['K']) for f, v in fams.items()}
                    out[cell, C.mname(m), round(r, 6), lab] = min(cost, key=cost.get) if cost else None
    return out


def load_rule(specs):
    """K_rho per series from the base instances of the main study (30 seeds)."""
    import fleet_scan
    fast_core = str(STUDY_ROOT / 'solver' / 'common')
    if fast_core not in sys.path:
        sys.path.insert(0, fast_core)
    from core import load_index
    bases = {}
    out = {}
    for sp in specs:
        cell, fam = sp['cell'], sp['family']
        if cell not in bases:
            ds = []
            for s in sorted(sp['base'], key=int):
                d = json.loads((STUDY_ROOT / 'main' / sp['base'][s]).read_text(encoding='utf8'))
                T, tE, n = d['tasks'], d['tauE'], len(d['tasks'])
                e = sum(tE[i][j] for i in range(n) for j in range(n) if i != j) / (n * (n - 1))
                m = d['meta']
                assert not m.get('delta_turn_s')
                ds.append(dict(mass=[t['mass'] for t in T], D=[t['load'] + t['tauL'] + t['unload'] for t in T], e=e,
                               delta=m['delta_s'], kappa=m['max_team'], H=m['n_batches'] * m['batch_len_s']))
            bases[cell] = ds
        kr = None
        for K in range(fleet_scan.kmin_of(fam), 61):                 # instance_setup.min_K: 3 for homogeneous, h + 1 for mixes
            caps = fleet_scan.caps_of(fam, K)
            v = []
            for x in bases[cell]:
                li = load_index(caps, x['mass'], x['D'], x['delta'], x['e'], x['kappa'], H=x['H'])
                if li is None:
                    v = None
                    break
                v.append(li['rho_star'])
            if v is not None and st.mean(v) <= 1.0:
                kr = K
                break
        out[sp['name']] = kr
    return out


def main():
    L = ['# Main study: summary of results (30 day instances, 120-min delay cap)', '',
         'Generated by `code/report_main.py`; the rules are given in the script docstring.', '']
    fr = rcsv(RES / 'main_fleets.csv')
    specs = json.loads((STUDY_ROOT / 'main' / 'series.json').read_text(encoding='utf8'))
    by = {r['series']: r for r in fr}
    # 1 counts vs the earlier ten-instance scan
    d = [(r, ival(r['K_final']) - ival(r['K_start'])) for r in fr]
    unchk = [r['series'] for r in fr if r['boundary_checked'] != 'True']
    L += ['## 1. Fleet counts compared with the counts of the earlier ten-instance scan', '',
          '| K* − K_start | series |', '| --- | --- |'] + ['| %+d | %d |' % (k, sum(x == k for _, x in d)) for k in sorted({x for _, x in d})]
    L += ['', '- series with a higher count: ' + ', '.join('%s (%s→%s)' % (r['series'], r['K_start'], r['K_final']) for r, x in d if x > 0),
          '- series lower by 2 or more: ' + ', '.join('%s (%s→%s)' % (r['series'], r['K_start'], r['K_final']) for r, x in d if x <= -2),
          '- series with an unfinished boundary check: %s (each of the two boundary rounds lowered the count by '
          'one, which reached the limit of two rounds; K* − 1 was not checked and the count may be lower still)'
          % ', '.join(unchk)]
    liu = {r['family']: ival(r['K_final']) for r in fr if r['cell'] == 'liu_short_baseline'}
    L += ['- K* per fleet type in the Liu condition (`liu_short_baseline`): ' + ', '.join('%s %s' % (f, k) for f, k in sorted(liu.items(), key=lambda x: x[1])),
          '- smallest K* over all 384 series: %d' % min(ival(r['K_final']) for r in fr), '']
    # 3 search dependence
    main = rcsv(RES / 'main_decisions.csv')
    L += ['## 3. Search dependence of the decisions (main grid, 6,480 decisions; the lower bounds proved no count '
          'infeasible, so the "proven" set is empty)', '',
          '| labour measure | decisions | search-dependent | share |', '| --- | --- | --- | --- |']
    for lab in C.LAB4:
        g = [x for x in main if x['labour'] == lab]
        k = sum(x['status'] == 'search-dependent' for x in g)
        L.append('| %s | %d | %d | %.1f%% |' % (lab, len(g), k, 100 * k / len(g)))
    k = sum(x['status'] == 'search-dependent' for x in main)
    ms = [float(x['margin']) for x in main]
    L += ['| total | %d | %d | %.1f%% |' % (len(main), k, 100 * k / len(main)), '',
          'lead of the winner over the runner-up: median %.2f%%; below 1%%: %d; below 0.1%%: %d; smallest %.4f%%.' % (
              100 * st.median(ms), sum(x < 0.01 for x in ms), sum(x < 0.001 for x in ms), 100 * min(ms)), '']
    # 4 after-shift labour
    summ = json.loads((RES / 'main_decisions_summary.json').read_text(encoding='utf8'))
    rep = json.loads((RES / 'main_replay.json').read_text(encoding='utf8'))
    ah = [r for r in fr if float(r['after_h'] or 0) > 0]
    fail = sorted(s for s, v in rep.items() if v and not v['meets_shift_hard'])
    L += ['## 4. After-shift work', '',
          '- the fourth labour measure (shift + 1.5 × 4 × after-shift transporter-hours) changes the winner relative '
          'to the shift measure: %d / %d (main grid: 5 price models × 9 r × 36 conditions).' % (
              summ['after_shift_changed'], summ['after_shift_of']),
          '- series whose pricing-selected schedules include after-shift work: %d / 384; mean after-shift '
          'transporter-hours per instance: median %.2f h, max %.2f h.' % (
              len(ah), st.median(float(r['after_h']) for r in ah) if ah else 0, max((float(r['after_h']) for r in ah), default=0)),
          '- series that no longer meet the target under a hard shift end (completion after 16 h counts as late), '
          'that is, meet it only with after-shift work: %d / 384; by handling × due date: %s; the %d that still '
          'meet it: %s.' % (
              len(fail), ', '.join('%s %d/%d' % (g, sum(1 for x in fail if '_%s_' % g.split()[0] in x and x.split('_')[2] == g.split()[1]),
                                                sum(1 for r in fr if r['cell'].split('_')[1:] == g.split()))
                                   for g in ('short baseline', 'short tight', 'massdep baseline', 'massdep tight', 'long baseline', 'long tight')),
              384 - len(fail), ', '.join(sorted(set(by) - set(fail))))]
    rs9 = C.main_r()
    full = fleets_at(fr, 'final')
    w_all = winners(full, (('affine',),), rs9, ('shift_h',))
    chk = winners(full, C.MAIN_MODELS, rs9, C.LAB4)
    assert all(chk[x['cell'], x['model'], round(float(x['r']), 6), x['labour']] == x['winner'] for x in main), 'winner mismatch'
    w_hard = winners({k: v for k, v in full.items() if '%s_%s' % k not in fail}, (('affine',),), rs9, ('shift_h',),
                     cells=sorted({c for c, _ in full}))
    L += ['- without these series, the winner changes in %d of the 324 decisions with the main price model, the 9 '
          'calibrated r and shift labour; in %d conditions no fleet type is left.' % (
        sum(w_all[k] != w_hard[k] for k in w_all), len({k[0] for k in w_hard if w_hard[k] is None})),
          '- reason (structural): the last batch of each day (12 / 97 blocks, 12.4%%) is released at 14 h with due '
          'times up to 17.5 h and on its own exceeds the 5%% allowance of late blocks; the 16-h hard end in effect '
          'tests "can the last batch be completed within 2 h of its release"; the %d series that pass are all '
          'short-handling (`short`) conditions.' % (384 - len(fail)), '']
    # 5 handling variability
    ok = [v for v in rep.values() if v]
    gap = [100 * (v['replay_on_nominal'] - v['replay_on_pert']) for v in ok]
    L += ['## 5. Handling variability (pricing-selected schedules at K*, 20 scenarios per instance, '
          'handling × U(0.5, 1.5))', '',
          '- drop in on-time rate (nominal − perturbed, percentage points): median %.2f, range %.2f–%.2f; series with '
          'a mean perturbed on-time rate below 95%%: %d / %d.' % (
              st.median(gap), min(gap), max(gap), sum(v['replay_on_pert'] < 0.95 for v in ok), len(ok)),
          '- share of (instance, scenario) pairs with a delay above 120 min: median %.1f%%, max %.1f%%; '
          'largest delay %.0f min.' % (
              100 * st.median(v['replay_share_over'] for v in ok), 100 * max(v['replay_share_over'] for v in ok),
              max(v['replay_max_tard_s'] for v in ok) / 60), '']
    # 6 pooling across fleet families
    pool = json.loads((RES / 'family_pooling.json').read_text(encoding='utf8'))
    low = {s: v for s, v in pool.items() if v.get('K_pooled') is not None and v['K_pooled'] < v['K_own']}
    pf = {}
    for s, v in pool.items():
        if v.get('K_pooled') is not None:
            pf[v['cell'], v['family']] = dict(K=v['K_pooled'], crew_veh_h=v['crew_veh_h'], crew_team_h=v['crew_team_h'], after_h=None)
    w_own = winners(full, C.MAIN_MODELS, rs9, C.LAB3)
    w_pool = winners(pf, C.MAIN_MODELS, rs9, C.LAB3)
    chp = [k for k in w_own if w_own[k] != w_pool.get(k)]
    L += ['## 6. Dominance pooling across fleet families (main-study runs only)', '',
          '- series with a lower count after pooling: %d / %d: %s' % (len(low), len(pool), ', '.join('%s (%d→%d)' % (s, v['K_own'], v['K_pooled']) for s, v in sorted(low.items()))),
          '- number of sources (distinct source series used by the pooled pricing-selected schedules): '
          'median %s, max %s' % (
              st.median(v['n_sources'] for v in pool.values() if v.get('n_sources')), max(v['n_sources'] for v in pool.values() if v.get('n_sources'))),
          '- winner changes on the main grid (3 labour measures, 4,860 decisions): %d, in conditions %s' % (len(chp), sorted({k[0] for k in chp})), '']
    # 7 search-intensity levels
    greedy = json.loads((RES / 'greedy_level.json').read_text(encoding='utf8'))
    lev_w = {lev: winners(fleets_at(fr, lev), C.MAIN_MODELS, rs9, ('shift_h',)) for lev in LEVELS}
    fin = lev_w['final']
    kf = {r['series']: ival(r['K_final']) for r in fr}
    rows7 = []
    for r in fr:
        rows7.append(dict(series=r['series'], cell=r['cell'], family=r['family'], coop_share=float(r['coop_share'] or 0),
                          **{'K_' + lev: ival(r['K_' + lev]) for lev in LEVELS}))
    cps = checkpoint_times(specs)
    L += ['## 7. Search-intensity levels (main grid, shift labour, 1,620 decisions; a fleet type whose count at a '
          'level does not meet the target is not eligible at that level)', '',
          '| level | agree | agreement | count = K* | +1 | +2 or more | above the scan limit | '
          'time (median share of the full run) |',
          '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for lev in LEVELS:
        agree = sum(lev_w[lev].get(k) == v for k, v in fin.items())
        dk = [(x['K_' + lev] - kf[x['series']]) if x['K_' + lev] is not None else None for x in rows7]
        t = cps.get(lev)
        L.append('| %s | %d | %.1f%% | %d | %d | %d | %d | %s |' % (
            lev, agree, 100 * agree / len(fin), sum(v == 0 for v in dk), sum(v == 1 for v in dk),
            sum(v is not None and v >= 2 for v in dk), sum(v is None for v in dk), t or '—'))
    gw = [v['wall_s'] for v in greedy.values()]
    L += ['', 'greedy level: median wall-clock time of the full scan of a series (several counts × 30 instances) '
          '%.0f s. Counts below K* (a level can only be weaker, so any such case would mean an error in the '
          'qualification or the embedding): %d.' % (
        st.median(gw), sum(1 for x in rows7 for lev in LEVELS if x['K_' + lev] is not None and x['K_' + lev] < kf[x['series']])), '']
    strata = (('K* ≤ 5', lambda x: kf[x['series']] <= 5), ('K* 6–10', lambda x: 6 <= kf[x['series']] <= 10),
              ('K* > 10', lambda x: kf[x['series']] > 10), ('coupled share 0', lambda x: x['coop_share'] == 0),
              ('coupled share (0, 0.3]', lambda x: 0 < x['coop_share'] <= 0.3), ('coupled share > 0.3', lambda x: x['coop_share'] > 0.3))
    L += ['share of series with a count equal to K*, by stratum:', '', '| stratum | series | ' + ' | '.join(LEVELS) + ' |', '| --- | --- |' + ' --- |' * len(LEVELS)]
    for name, f in strata:
        g = [x for x in rows7 if f(x)]
        L.append('| %s | %d | ' % (name, len(g)) + ' | '.join('%.0f%%' % (100 * sum(x['K_' + lev] == kf[x['series']] for x in g) / len(g)) if g else '—'
                                                          for lev in LEVELS) + ' |')
    with open(RES / 'main_search_levels.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows7[0]))
        w.writeheader()
        w.writerows(rows7)
    # 8 load rule
    lp = RES / 'main_load_rule.csv'
    if '--reuse-loadrule' in sys.argv and lp.exists():
        kr = {r['series']: ival(r['K_rho']) for r in rcsv(lp)}
    else:
        kr = load_rule(specs)
    lr = []
    for sp in specs:
        k = kf[sp['name']]
        lr.append(dict(series=sp['name'], cell=sp['cell'], family=sp['family'], K_star=k, K_rho=kr[sp['name']],
                       d=None if kr[sp['name']] is None else k - kr[sp['name']]))
    with open(RES / 'main_load_rule.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(lr[0]))
        w.writeheader()
        w.writerows(lr)
    L += ['', '## 8. Input-only load rule (K_rho: smallest count with ρ* averaged over the 30 instances ≤ 1; '
          'd = K* − K_rho, positive = underestimate)', '',
          '| due dates | series | K_rho = K* | abs(d) ≤ 1 | mean d | min d | max d (largest underestimate) |',
          '| --- | --- | --- | --- | --- | --- | --- |']
    for due in ('baseline', 'tight'):
        e = [x['d'] for x in lr if x['cell'].endswith(due) and x['d'] is not None]
        L.append('| %s | %d | %d | %d | %.2f | %d | %d |' % (due, len(e), sum(v == 0 for v in e), sum(abs(v) <= 1 for v in e), st.mean(e), min(e), max(e)))
    # 9 cross-yard: main-case Liu-mass conditions vs the second case's from-scratch winner (425 t at every calibrated r)
    L += ['', '## 9. Consistency across yards: main-case Liu-mass conditions vs from-scratch sizing in the '
          'second case', '',
          'Main price model (affine), the 9 calibrated r, shift labour (main case 4 × 16 h × K). Second case '
          '(`second_case_summary.md`, 4 × 10 h × K): at k = 6 and 8, 425 t is cheapest at every r.', '',
          '| condition | winner among all 11 fleet types (r from low to high) | winner among homogeneous fleets only |',
          '| --- | --- | --- |']
    homo = {k: v for k, v in full.items() if not k[1].startswith('MX')}
    w_h = winners(homo, (('affine',),), rs9, ('shift_h',))
    for cell in sorted({c for c, _ in full if c.startswith('liu')}):
        seq = lambda w: ' '.join(w[cell, 'affine', round(r, 6), 'shift_h'] for r in rs9)
        L.append('| %s | %s | %s |' % (cell, seq(w_all), seq(w_h)))
    (RES / 'main_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def checkpoint_times(specs):
    """Median share of the full run's wall time reached at each checkpoint (j = 0 runs)."""
    share = {0: [], 100: [], 300: []}
    for sp in specs:
        for p in (STUDY_ROOT / 'main' / 'runs' / sp['name']).glob('*_j0.json'):
            r = json.loads(p.read_text(encoding='utf8'))
            if r['status'] != 'OK' or not r['wall_s']:
                continue
            for c in r['checkpoints']:
                if c['it'] in share and c.get('wall') is not None:
                    share[c['it']].append(c['wall'] / r['wall_s'])
    out = {'cp%d' % k: '%.0f%%' % (100 * st.median(v)) for k, v in share.items() if v}
    out['single'] = '100%'
    out['final'] = '100% (plus 2 runs at K* − 1)'
    return out


if __name__ == '__main__':
    main()
