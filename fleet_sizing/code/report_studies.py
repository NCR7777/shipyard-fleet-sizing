"""Reports of the studies that finish after the main study: the heavy-block share study (directory `heavy_share`), the price
of overweight-only coupling (PoR; overweight-only coupling runs, directory `overweight_only`) and the decision boundaries of the
one-factor sensitivity study (directory `sensitivity`).

Counts come from analyse_study on each study (own-series runs, embedding, boundary check); pricing is the main grid of
cost_decisions (5 price models x 9 r x 4 labour measures); a type without a qualifying count is not eligible in that setting.
Search dependence as in cost_decisions.decisions: search-dependent if a losing type with K - 1 >= its floor would be
cheaper at K - 1.

  python report_studies.py heavy_share | overweight_only | sensitivity      -> results/E7_*.csv|md, R4R_*.csv|md, E5_*.csv|md
  python report_studies.py selfcheck
"""
import csv
import json
import statistics as st
from collections import Counter
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(HERE))
import cost_decisions as C                                      # noqa: E402

RS = C.main_r()


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def write(path, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def fleet_row(r):
    return dict(K=int(r['K_final']), crew_veh_h=float(r['crew_veh_h'] or 0), crew_team_h=float(r['crew_team_h'] or 0),
                after_h=float(r['after_h'] or 0))


def study_fleets(study):
    """series -> (cell, family, fleet row or None) from analyse_study on the study."""
    import analyse_study as A
    rows = A.analyse(STUDY_ROOT / study)
    out = {}
    for r in rows:
        ok = r['K_final'] not in (None, '', 'None')
        out[r['series']] = (r['cell'], r['family'], fleet_row(r) if ok else None)
    with open(RES / ('%s_fleets.csv' % study), 'w', encoding='utf-8-sig', newline='') as f:
        keys = []
        for r in rows:                              # rows without a count lack the pricing columns
            keys += [k for k in r if k not in keys]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return out


def decide(cell, fams, P, r, lab):
    """fams: family -> fleet row. Returns (winner, cost, status) with the search-dependence rule;
    (None, None, None) if empty."""
    if not fams:
        return None, None, None
    cost = {f: r * P(C.caps(cell, f, v['K'])) + C.labour(v, lab, v['K']) for f, v in fams.items()}
    w = min(cost, key=cost.get)
    risky = [f for f, v in fams.items() if f != w and v['K'] - 1 >= C.floor_of(f)
             and r * P(C.caps(cell, f, v['K'] - 1)) + C.labour(v, lab, v['K'] - 1) < cost[w]]
    return w, cost[w], 'search-dependent' if risky else 'certain'


def threshold(ps, winners, tier='550'):
    """Threshold: the upper interval of p in which `tier` wins -> its lower end."""
    idx = [i for i, w in enumerate(winners) if w == tier]
    if not idx:
        return 'none in grid'
    if idx == list(range(idx[0], len(ps))):
        return '%.2f' % ps[idx[0]]
    return 'no single threshold (%s)' % ' '.join('%.2f:%s' % (p, w) for p, w in zip(ps, winners))


def cls(f):
    return 'single-carry tier' if f == '550' else ('mix' if f.startswith('MX') else 'coupling tier')


def heavy_share():
    fl = study_fleets('heavy_share')
    by = {}
    for s, (cell, fam, v) in fl.items():
        if v:
            by.setdefault(cell, {})[fam] = v
    ps = sorted({float(c.split('_')[0][len('heavy'):]) for c in by})
    rows, thr = [], []
    for m in C.MAIN_MODELS:
        P = C.proxy(m)
        for hs in ('short', 'massdep'):
            for lab in C.LAB4:
                for r in RS:
                    ws = []
                    for p in ps:
                        cell = 'heavy%.2f_%s_baseline' % (p, hs)
                        w, c, stt = decide(cell, by.get(cell, {}), P, r, lab)
                        ws.append(w)
                        rows.append(dict(p=p, handling=hs, model=C.mname(m), r=round(r, 3), labour=lab, winner=w, winner_class=cls(w) if w else None,
                                         cost=c, status=stt, eligible=len(by.get(cell, {}))))
                    thr.append(dict(handling=hs, model=C.mname(m), labour=lab, r=round(r, 3), p_star=threshold(ps, ws)))
    write(RES / 'heavy_share_decisions.csv', rows)
    write(RES / 'heavy_share_thresholds.csv', thr)
    L = ['# Heavy-block share', '', 'Threshold p* for the 550 t tier (affine price, shift staffing):', '',
         '| handling | ' + ' | '.join('r = %.1f' % r for r in RS) + ' |', '| --- |' + ' --- |' * len(RS)]
    for hs in ('short', 'massdep'):
        L.append('| %s | ' % hs + ' | '.join(t['p_star'] for t in thr if t['handling'] == hs and t['model'] == 'affine' and t['labour'] == 'shift_h') + ' |')
    L += ['', 'Winner class by p (affine, shift staffing, all nine r):', '']
    for hs in ('short', 'massdep'):
        for p in ps:
            g = [x for x in rows if x['handling'] == hs and x['p'] == p and x['model'] == 'affine' and x['labour'] == 'shift_h']
            L.append('- %s, p = %.2f: %s; search-dependent %d / %d' % (hs, p, ', '.join(sorted({'%s (%s)' % (x['winner'], x['winner_class']) for x in g})),
                                                                  sum(x['status'] == 'search-dependent' for x in g), len(g)))
    (RES / 'heavy_share_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def overweight_only():
    flex = {(r['cell'], r['family']): fleet_row(r) for r in rcsv(RES / 'main_fleets.csv')}
    rig = {}
    for s, (cell, fam, v) in study_fleets('overweight_only').items():
        if v:
            rig[cell, fam] = v
    rows = []
    for m in C.MAIN_MODELS:
        P = C.proxy(m)
        for cell in sorted({c for c, _ in flex}):
            ff = {f: v for (c, f), v in flex.items() if c == cell}
            fr = {f: v for f, v in ff.items() if not f.startswith('MX')}
            fr.update({f: v for (c, f), v in rig.items() if c == cell})
            for r in RS:
                for lab in C.LAB4:
                    wf, cf, _ = decide(cell, ff, P, r, lab)
                    wr, cr, _ = decide(cell, fr, P, r, lab)
                    rows.append(dict(cell=cell, model=C.mname(m), r=round(r, 3), labour=lab, winner_flex=wf, winner_rigid=wr,
                                     por=cr / cf - 1, mixes_qualified_rigid=sum(1 for f in fr if f.startswith('MX'))))
    write(RES / 'overweight_only_por.csv', rows)
    L = ['# PoR: price of overweight-only coupling', '', '| labour | settings | PoR > 0 | PoR < 0 | median | max |',
         '| --- | --- | --- | --- | --- | --- |']
    for lab in C.LAB4:
        g = [x['por'] for x in rows if x['labour'] == lab]
        L.append('| %s | %d | %d | %d | %.2f%% | %.2f%% |' % (lab, len(g), sum(v > 1e-12 for v in g), sum(v < -1e-12 for v in g),
                                                         100 * st.median(g), 100 * max(g)))
    (RES / 'overweight_only_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


SENS_FACTORS = {   # ordered levels including the baseline ('base')
    'coupling time (min)': [('delta0', 0), ('base', 10), ('delta20', 20), ('delta30', 30), ('delta40', 40)],
    'handling factor': [('hand0.5', 0.5), ('hand0.67', 0.67), ('base', 1), ('hand1.5', 1.5), ('hand2.0', 2.0)],
    'speed factor': [('speedL22', 'Liu 50/30 m/min'), ('speed0.5', 0.5), ('speed0.75', 0.75), ('base', 1)],
    'largest team': [('team2', 2), ('base', 3)],
    'turn time (s)': [('base', 0), ('tau30', 30)],
    'coupled-turn time (s)': [('base', 0), ('dtau30', 30), ('dtau60', 60)],
}
SENS_TYPES = ('270', '300', '380', '550', 'MX2')


def sensitivity():
    e5f = study_fleets('sensitivity')
    lev = {}
    for s, (cell, fam, v) in e5f.items():
        if v:
            lev.setdefault(s.split('_')[0], {}).setdefault(cell, {})[fam] = v
    base = {}
    for r in rcsv(RES / 'main_fleets.csv'):
        if r['family'] in SENS_TYPES and r['cell'] in {c for d in lev.values() for c in d}:
            base.setdefault(r['cell'], {})[r['family']] = fleet_row(r)
    lev['base'] = base
    cells = sorted(base)
    rows, summ = [], []
    for fac, levels in SENS_FACTORS.items():
        b = [k for k, _ in levels].index('base')
        for m in C.MAIN_MODELS:
            P = C.proxy(m)
            for cell in cells:
                for r in RS:
                    for lab in C.LAB4:
                        w = [decide(cell, lev.get(k, {}).get(cell, {}), P, r, lab) for k, _ in levels]
                        rec = dict(factor=fac, cell=cell, model=C.mname(m), r=round(r, 3), labour=lab, base_winner=w[b][0])
                        for side, rng in (('below', range(b - 1, -1, -1)), ('above', range(b + 1, len(levels)))):
                            prev, hit = levels[b][1], None
                            for i in rng:
                                if w[i][0] != w[b][0]:
                                    hit = (prev, levels[i][1], w[i][0], w[i][2])
                                    break
                                prev = levels[i][1]
                            rec[side] = 'unchanged' if hit is None else 'between %s and %s -> %s (%s)' % hit
                        rows.append(rec)
        for side in ('below', 'above'):
            g = [x[side] for x in rows if x['factor'] == fac]
            ch = Counter(x.split(' -> ')[0] for x in g if x != 'unchanged')
            summ.append(dict(factor=fac, direction=side, settings=len(g), changed=sum(ch.values()),
                             nearest=' | '.join('%s: %d' % kv for kv in sorted(ch.items()))))
    write(RES / 'sensitivity_boundaries.csv', rows)
    write(RES / 'sensitivity_boundary_summary.csv', summ)
    L = ['# Decision boundaries of the one-factor sensitivity study', '', '| factor | direction | settings | winner changes | first change |',
         '| --- | --- | --- | --- | --- |'] + ['| %s | %s | %d | %d | %s |' % (x['factor'], x['direction'], x['settings'], x['changed'], x['nearest'] or '—')
                                               for x in summ if not (x['settings'] == 0)]
    (RES / 'sensitivity_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def selfcheck():
    ps = [0.0, 0.02, 0.05, 0.10, 0.20, 0.35, 0.50]
    assert threshold(ps, ['MX2', 'MX2', '300', '550', '550', '550', '550']) == '0.10'
    assert threshold(ps, ['MX2'] * 7) == 'none in grid'
    assert threshold(ps, ['MX2', '550', 'MX2', '550', '550', '550', '550']).startswith('no single threshold')
    fams = {'550': dict(K=5, crew_veh_h=0, crew_team_h=0, after_h=0), '300': dict(K=8, crew_veh_h=0, crew_team_h=0, after_h=0)}
    P = C.proxy(('affine',))
    w, c, s = decide('rohcha_short_baseline', fams, P, 12.4, 'shift_h')
    assert w == '550' and s == 'certain', (w, s)
    assert decide('rohcha_short_baseline', {}, P, 12.4, 'shift_h') == (None, None, None)
    print('report_studies self-check passed')


if __name__ == '__main__':
    {'heavy_share': heavy_share, 'overweight_only': overweight_only, 'sensitivity': sensitivity, 'selfcheck': selfcheck}[sys.argv[1]]()
