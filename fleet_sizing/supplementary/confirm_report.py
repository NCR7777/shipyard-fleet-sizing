"""Reports of the supplementary studies against the checks in their design files (`supplementary/design`).

  python confirm_report.py fresh-days            # needs results/fresh_days_fleets.csv   (analyse_study.py fresh_days)
  python confirm_report.py extended-mixes            # needs results/extended_mixes_fleets.csv   (analyse_study.py extended_mixes)
  python confirm_report.py slow-handling            # uses sensitivity_fleets.csv and, when present, unresolved_scan*_fleets.csv, candidates_*_fleets.csv, sensitivity_precheck.csv
  python confirm_report.py selfcheck     # s3 recomputation on the main sensitivity results must reproduce results/sensitivity_levels.csv
Each writes results/<S>_decisions.csv, results/<S>_report.json and results/<S>_report.md (all settings, nothing dropped).
"""
import csv
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(STUDY_ROOT / 'code'))
import cost_decisions as RC                                   # noqa: E402

CR = 0.10


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def fleet_rows(p, keep=lambda r: True):
    """(cell, family) -> pricing row (qualified series only), coupled share, and the unqualified series."""
    fl, coop, open_ = {}, {}, []
    for r in rcsv(p):
        if not keep(r):
            continue
        if r['K_final'] in ('', 'None', None):
            open_.append(r['series'])
            continue
        k = (r['cell'], r['family'])
        fl[k] = dict(K=int(float(r['K_final'])), crew_veh_h=float(r['crew_veh_h']), crew_team_h=float(r['crew_team_h']),
                     after_h=float(r['after_h']))
        coop[k] = float(r['coop_share'])
    return fl, coop, open_


def settings():
    for m in RC.MAIN_MODELS:
        for r in RC.main_r():
            for lab in RC.LAB4:
                yield m, r, lab


def priced(fl, cell, fams, m, r, lab):
    P = RC.proxy(m)
    return {f: r * P(RC.caps(cell, f, fl[cell, f]['K'])) + RC.labour(fl[cell, f], lab, fl[cell, f]['K']) for f in fams}


def write(name, rows, rep, md):
    with open(RES / ('%s_decisions.csv' % name), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (RES / ('%s_report.json' % name)).write_text(json.dumps(rep, indent=1, ensure_ascii=False) + '\n', encoding='utf8')
    (RES / ('%s_report.md' % name)).write_text('\n'.join(md) + '\n', encoding='utf8')
    print('\n'.join(md))


def _pct(v):
    return '-' if v is None else '%.1f %%' % (100 * v)


def share(xs):
    xs = list(xs)
    return (sum(xs) / len(xs)) if xs else None


# ------------------------------------------------------------------ fresh-day confirmation
def fresh_days():
    P = json.loads((HERE / 'design' / 'fresh_days.json').read_text(encoding='utf8'))
    fl, coop, open_ = fleet_rows(RES / 'fresh_days_fleets.csv')
    rows = []
    for cell, c in P['conditions'].items():
        fams = [f for f in c['families'] if (cell, f) in fl]
        pred = {(p['model'], p['r'], p['labour']): p for p in c['predicted']}
        for m, r, lab in settings():
            p = pred[RC.mname(m), round(r, 6), lab]
            cost = priced(fl, cell, fams, m, r, lab)
            w = min(cost, key=cost.get) if cost else None
            s = sorted(cost.values())
            rows.append(dict(cell=cell, model=RC.mname(m), r=round(r, 6), labour=lab, winner=w, K=fl[cell, w]['K'] if w else None,
                             coop=coop.get((cell, w)), margin=(s[1] / s[0] - 1) if len(s) > 1 else None,
                             predicted=p['winner'], predicted_margin=p['margin'], same=w == p['winner']))
    ex = [x for x in rows if not x['cell'].startswith('extraheavy') and x['winner']]
    m4 = [x for x in rows if x['cell'].startswith('extraheavy') and x['winner']]
    dk = []
    for cell, c in P['conditions'].items():
        for f, v in c['families'].items():
            if (cell, f) in fl:
                dk.append(fl[cell, f]['K'] - v['K_start'])
    rep = dict(
        settings=len(rows), undecided=sum(x['winner'] is None for x in rows), unqualified_series=open_,
        P1_agreement=share(x['same'] for x in rows if x['winner']),
        P1_by_condition={c: share(x['same'] for x in rows if x['cell'] == c and x['winner']) for c in P['conditions']},
        P1_by_labour={l: share(x['same'] for x in rows if x['labour'] == l and x['winner']) for l in RC.LAB4},
        P1_disagreements_with_predicted_margin_below_2pct=share(x['predicted_margin'] < 0.02 for x in rows if x['winner'] and not x['same']),
        P2_single_carry_outside_extraheavy=share(x['coop'] <= CR for x in ex), P2_met=(share(x['coop'] <= CR for x in ex) or 0) >= 0.95,
        P3_extraheavy_winners=dict(Counter(x['winner'] for x in m4)), P3_extraheavy_winner_coop=dict(Counter(round(x['coop'], 3) for x in m4)),
        P4_share_abs_dK_le_1=share(abs(d) <= 1 for d in dk), P4_dK=dict(Counter(dk)), P4_met=(share(abs(d) <= 1 for d in dk) or 0) >= 0.9)
    md = ['# Fresh-day confirmation (days %d-%d)' % (P['seeds'][0], P['seeds'][-1]), '',
          '| check | result |', '| --- | --- |',
          '| check 1: winner agreement | %.1f %% of %d decided settings |' % (
              100 * rep['P1_agreement'], len(rows) - rep['undecided']),
          '| check 2: single carry outside the extra-heavy scenario | %.1f %% |' % (
              100 * rep['P2_single_carry_outside_extraheavy']),
          '| check 3: winners in the extra-heavy scenario | %s |' % rep['P3_extraheavy_winners'],
          '| check 4: abs(dK) <= 1 | %.1f %% of series; dK %s |' % (100 * rep['P4_share_abs_dK_le_1'], rep['P4_dK']),
          '', 'By condition: ' + ', '.join('%s %.0f %%' % (c, 100 * v) for c, v in rep['P1_by_condition'].items() if v is not None)]
    write('fresh_days', rows, rep, md)


# ------------------------------------------------------------------ extended light-heavy mixes
def extended_mixes():
    P = json.loads((HERE / 'design' / 'extended_mixes.json').read_text(encoding='utf8'))
    cells = set(P['conditions'])
    fl, coop, _ = fleet_rows(RES / 'main_fleets.csv', lambda r: r['cell'] in cells)
    f4, c4, open_ = fleet_rows(RES / 'extended_mixes_fleets.csv')
    fl.update(f4)
    coop.update(c4)
    rows = []
    for cell, c in P['conditions'].items():
        ext = [f for f in c['families'] if (cell, f) in fl]
        pack = sorted(f for (cc, f) in fl if cc == cell and not f.startswith('L'))
        grid = sorted(int(f.split('x')[1]) for f in c['families'])
        for m, r, lab in settings():
            cost = priced(fl, cell, pack + ext, m, r, lab)
            w = min(cost, key=cost.get)
            bp = min(pack, key=cost.get)
            be = min(ext, key=cost.get) if ext else None
            n = int(be.split('x')[1]) if be else None
            rows.append(dict(cell=cell, model=RC.mname(m), r=round(r, 6), labour=lab, winner=w, winner_coop=coop[cell, w],
                             best_packaged=bp, best_ext=be, n=n, n_star=c['n_star'], edge=n in (grid[0], grid[-1]) if n else None,
                             ext_coop=coop.get((cell, be)), ext_wins=w == be,
                             premium_packaged_over_ext=(cost[bp] / cost[be] - 1) if be else None))
    by = {}
    for x in rows:
        if x['n'] is not None:
            by.setdefault(x['cell'], Counter())[x['n']] += 1
    p1 = {c: dict(n_star=P['conditions'][c]['n_star'], modal_n=cnt.most_common(1)[0][0], counts=dict(cnt)) for c, cnt in by.items()}
    rep = dict(
        settings=len(rows), unqualified_series=open_,
        P1_hits=sum(v['modal_n'] == v['n_star'] for v in p1.values()), P1_of=len(p1), P1=p1,
        P2_share_abs_n_minus_nstar_le_1=share(abs(x['n'] - x['n_star']) <= 1 for x in rows if x['n'] is not None),
        P2_best_at_grid_edge=share(x['edge'] for x in rows if x['n'] is not None),
        P3_ext_single_carry=share(x['ext_coop'] <= CR for x in rows if x['best_ext']),
        P4_ext_wins=share(x['ext_wins'] for x in rows),
        P4_premium_median=st.median(x['premium_packaged_over_ext'] for x in rows if x['best_ext']),
        winner_single_carry=share(x['winner_coop'] <= CR for x in rows))
    md = ['# Extended light-heavy mixes in 13 conditions', '',
          '| check | result |', '| --- | --- |',
          '| check 1: modal n = n* | %d / %d conditions |' % (rep['P1_hits'], rep['P1_of']),
          '| check 2: abs(n - n*) <= 1 | %.1f %% of settings (best at grid edge: %.1f %%) |' % (
              100 * rep['P2_share_abs_n_minus_nstar_le_1'], 100 * rep['P2_best_at_grid_edge']),
          '| check 3: cheapest mix couples <= 10 %% | %.1f %% |' % (100 * rep['P3_ext_single_carry']),
          '| check 4: an extended mix is cheapest | %.1f %%; median premium of the best main-study fleet %.2f %% |' % (
              100 * rep['P4_ext_wins'], 100 * rep['P4_premium_median']),
          '| winner couples <= 10 %% (all families) | %.1f %% |' % (100 * rep['winner_single_carry']), '',
          '| condition | n* | modal n | counts |', '| --- | --- | --- | --- |'] + \
         ['| %s | %d | %d | %s |' % (c, v['n_star'], v['modal_n'], v['counts']) for c, v in sorted(p1.items())]
    write('extended_mixes', rows, rep, md)


# ------------------------------------------------------------------ slow speed / long handling
LEVELS = ('speedliu', 'speed0.5', 'speed0.75', 'hand1.5', 'hand2.0')


def slow_handling_levels(with_new=True, with_f2=False):
    lev, coop = {}, {}
    srcs = [(RES / 'sensitivity_fleets.csv', lambda s: s.split('_')[0])]
    if with_new:
        srcs += [(p, lambda s: s.split('_')[0]) for p in sorted(RES.glob('unresolved_scan*_fleets.csv'))]
        srcs += [(p, lambda s: s.split('_')[1]) for p in sorted(RES.glob('candidates_*_fleets.csv'))]
    for p, fac_of in srcs:
        if not p.exists():
            continue
        for r in rcsv(p):
            fac = fac_of(r['series'])
            if fac not in LEVELS:
                continue
            k = (fac, r['cell'], r['family'])
            if r['K_final'] in ('', 'None'):
                lev.pop(k, None)                         # a later file may still leave it open
                continue
            lev[k] = dict(K=int(float(r['K_final'])), crew_veh_h=float(r['crew_veh_h']), crew_team_h=float(r['crew_team_h']),
                          after_h=float(r['after_h']))
            coop[k] = float(r['coop_share'])
    rows, f2 = [], []
    cells = sorted({c for (_, c, _) in lev} | {r['cell'] for r in rcsv(RES / 'sensitivity_fleets.csv')})
    for fac in LEVELS:
        for cell in cells:
            fams = {f: v for (fa, c, f), v in lev.items() if fa == fac and c == cell}
            fl = {(cell, f): v for f, v in fams.items()}
            for m, r, lab in settings():
                cost = priced(fl, cell, list(fams), m, r, lab) if fams else {}
                w = min(cost, key=cost.get) if cost else None
                rows.append(dict(level=fac, cell=cell, model=RC.mname(m), r=round(r, 3), labour=lab, winner=w,
                                 coop=coop.get((fac, cell, w)), n_families=len(fams)))
                if lab == 'shift_h' and w:                # kappa test, shift labour: each light tier vs 550 t
                    P = RC.proxy(m)
                    for f in fams:
                        if f.isdigit() and int(f) < 550 and coop[fac, cell, f] > 0:
                            kappa = (r * P([550]) + 64) / (r * P([int(f)]) + 64) - 1
                            f2.append(dict(over=coop[fac, cell, f] > kappa, lost=f != w))
    return (rows, f2) if with_f2 else rows


def slow_handling():
    old = {(x['level'], x['cell'], x['model'], x['r'], x['labour']): x['winner'] for x in slow_handling_levels(False)}
    rows, f2 = slow_handling_levels(True, True)
    for x in rows:
        x['winner_packaged'] = old[x['level'], x['cell'], x['model'], x['r'], x['labour']]
    pc = RES / 'sensitivity_precheck.csv'
    pre = {r['series']: r for r in rcsv(pc)} if pc.exists() else {}
    dec = [x for x in rows if x['winner']]
    rep = dict(settings=len(rows), undecided_packaged=sum(x['winner_packaged'] is None for x in rows),
               undecided_now=sum(x['winner'] is None for x in rows),
               undecided_now_by=dict(Counter('%s %s' % (x['level'], x['cell']) for x in rows if x['winner'] is None)),
               precheck=dict(Counter(r['verdict'] for r in pre.values())),
               precheck_unattainable=sorted(s for s, r in pre.items() if r['verdict'] == 'unattainable'),
               P2_single_carry_decided=share(x['coop'] <= CR for x in dec),
               P2_by_level={l: share(x['coop'] <= CR for x in dec if x['level'] == l) for l in LEVELS},
               winner_changed_by_new_families=sum(1 for x in rows if x['winner_packaged'] and x['winner'] != x['winner_packaged']),
               P3_light_tiers_coupling_above_kappa=sum(x['over'] for x in f2),
               P3_of_which_lost=share(x['lost'] for x in f2 if x['over']),
               P3_light_tiers_below_kappa=sum(not x['over'] for x in f2),
               P3_of_which_lost_below=share(x['lost'] for x in f2 if not x['over']),
               winners_by_level={l: dict(Counter(x['winner'] for x in dec if x['level'] == l)) for l in LEVELS})
    md = ['# Slow speed and long handling', '',
          '- undecided settings: main results %d -> now %d (%s)' % (
              rep['undecided_packaged'], rep['undecided_now'], rep['undecided_now_by'] or 'none'),
          '- structural screen: %s; unattainable: %s' % (rep['precheck'] or 'not run', ', '.join(rep['precheck_unattainable']) or 'none'),
          '- winners coupling <= 10 %%: %.1f %% of decided settings; by level %s' % (
              100 * rep['P2_single_carry_decided'], {k: round(100 * v, 1) for k, v in rep['P2_by_level'].items() if v is not None}),
          '- settings whose winner changed when 425/500 t and mixes were added: %d' % rep['winner_changed_by_new_families'],
          '- kappa test under shift labour (coupled block share as proxy for h; kappa against 550 t): '
          'light tiers above kappa %d, '
          'of which lost %s; below kappa %d, of which lost %s' % (
              rep['P3_light_tiers_coupling_above_kappa'], _pct(rep['P3_of_which_lost']), rep['P3_light_tiers_below_kappa'],
              _pct(rep['P3_of_which_lost_below']))]
    write('slow_handling', rows, rep, md)


def selfcheck():
    """Recomputed winners on the main results of the one-factor sensitivity study (`sensitivity_fleets.csv`) equal
    `results/sensitivity_levels.csv` for the slow-speed and long-handling levels."""
    mine = {(x['level'], x['cell'], x['model'], x['r'], x['labour']): x['winner'] for x in slow_handling_levels(False)}
    ref = [r for r in rcsv(RES / 'sensitivity_levels.csv') if r['level'] in LEVELS]
    bad = [r for r in ref if (mine[r['level'], r['cell'], r['model'], round(float(r['r']), 3), r['labour']] or '') != r['winner']]
    assert ref and not bad, (len(ref), bad[:3])
    print('confirm_report self-check: %d sensitivity_levels winners reproduced' % len(ref))


if __name__ == '__main__':
    {'fresh-days': fresh_days, 'slow-handling': slow_handling, 'extended-mixes': extended_mixes, 'selfcheck': selfcheck}[sys.argv[1]]()
