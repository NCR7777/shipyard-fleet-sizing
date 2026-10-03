"""Tier-speed study: the cheapest fleet under the manufacturer speeds of each tier, in six conditions (Jiang, Roh-Cha
and Liu mass scenarios x short and mass-dependent handling, baseline due dates), on the main grid (5 price models x
9 r x 4 labour measures).

Every condition compares the eleven reference fleets, including the one- and two-heavy-member mixes `MX1` and `MX2`.
Counts under tier speeds (pessimistic end: mixes run with every member at the speed of their heavy units), by source
study directory:
  200, 250, 270, 300, 325 t                            `main` (12/6 km/h, manufacturer or assumed)
  380, 550 t, `MX2`                                    `tier_speeds`
  425, 500 t, `MX1`, Jiang masses                      `tier_speeds_jiang`
  425, 500 t, Liu masses                               `tier_speeds`
  `MX1`, Liu masses, short handling                    `tier_speeds` (all members 10/5, priced with 425 t heavy members)
  425, 500 t, `MX1`, Roh-Cha masses; `MX1`, Liu        `main` counts and hours as a bound (slower vehicles never
  masses, mass-dependent handling                      finish a block earlier)
Mixes run at 12/5 are priced with 550 t heavy members; mixes taken from the main study by the main substitution rule.
Optimistic end: `MX1` and `MX2` from the main study. Common speeds: all eleven from the main study; its winners must
equal main_decisions.csv.

  python report_tier_speeds.py              -> results/tier_speeds_decisions.csv, tier_speeds_summary.md
  python report_tier_speeds.py check-rohcha-liu   (rohcha and liu only; needs no tier_speeds_jiang counts)
  python report_tier_speeds.py selfcheck
"""
import csv
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cost_decisions as C                                      # noqa: E402
from report_studies import RES, RS, write                     # noqa: E402

CELLS = ['jiang_short_baseline', 'jiang_massdep_baseline', 'rohcha_short_baseline', 'rohcha_massdep_baseline', 'liu_short_baseline', 'liu_massdep_baseline']
FAMS = ('200', '250', '270', '300', '325', '380', '425', '500', '550', 'MX1', 'MX2')


def source(cell, f):
    """(study, heavy capacity for mix pricing or None for the main rule, bound?) under tier speeds, pessimistic end."""
    ms = cell.split('_')[0]
    if f in ('200', '250', '270', '300', '325'):
        return 'main', None, False
    if f in ('380', '550'):
        return 'tier_speeds', None, False
    if f == 'MX2':
        return 'tier_speeds', 550, False
    if f in ('425', '500'):
        return {'jiang': ('tier_speeds_jiang', None, False), 'liu': ('tier_speeds', None, False)}.get(ms, ('main', None, True))
    if ms == 'jiang':
        return 'tier_speeds_jiang', 550, False
    return ('tier_speeds', 425, False) if cell == 'liu_short_baseline' else ('main', None, True)


def load(path):
    out = {}
    for r in csv.DictReader(open(path, encoding='utf-8-sig')):
        if r['K_final'] not in (None, '', 'None'):
            out[r['cell'], r['family']] = dict(K=int(r['K_final']), crew_veh_h=float(r['crew_veh_h']), crew_team_h=float(r['crew_team_h']),
                                               after_h=float(r['after_h'] or 0), coop=float(r['coop_share'] or 0))
    return out


def cost(cell, fams, P, r, lab, k_off=0):
    """fams: family -> (fleet row, heavy capacity for mix pricing or None)."""
    out = {}
    for f, (v, hv) in fams.items():
        K = v['K'] + k_off
        caps = [hv] * int(f[-1]) + [270] * (K - int(f[-1])) if (f.startswith('MX') and hv) else C.caps(cell, f, K)
        out[f] = r * P(caps) + C.labour(v, lab, K)
    return out


def decide(cell, fams, P, r, lab):
    c = cost(cell, fams, P, r, lab)
    w = min(c, key=c.get)
    lower = cost(cell, fams, P, r, lab, -1)
    risky = any(f != w and fams[f][0]['K'] - 1 >= C.floor_of(f) and lower[f] < c[w] for f in fams)
    return w, c, 'search-dependent' if risky else 'certain'


def sets(cell, data, only=None):
    """common, pessimistic and optimistic candidate sets of one condition; data: study -> fleet table."""
    fs = [f for f in FAMS if only is None or f in only]
    common = {f: (data['main'][cell, f], None) for f in fs if (cell, f) in data['main']}
    pess = {}
    for f in fs:
        st, hv, _ = source(cell, f)
        if (cell, f) in data[st]:
            pess[f] = (data[st][cell, f], hv)
    opt = dict(pess, **{f: common[f] for f in ('MX1', 'MX2') if f in common and f in pess})
    return common, pess, opt


def analyse(data, cells, only=None):
    rows = []
    for cell in cells:
        common, pess, opt = sets(cell, data, only and only[cell.split('_')[0]])
        for m in C.MAIN_MODELS:
            P = C.proxy(m)
            for r in RS:
                for lab in C.LAB4:
                    wc, _, _ = decide(cell, common, P, r, lab)
                    wp, cp, st = decide(cell, pess, P, r, lab)
                    wo, _, _ = decide(cell, opt, P, r, lab)
                    rows.append(dict(cell=cell, model=C.mname(m), r=round(r, 3), labour=lab, winner_common=wc, winner_tier=wp,
                                     winner_tier_mix_opt=wo, status_tier=st, regret_common_winner=cp[wc] / cp[wp] - 1 if wc in cp else None,
                                     coop_tier=pess[wp][0]['coop'], coop_tier_opt=opt[wo][0]['coop']))
    return rows


def check_common(rows):
    """The common-speed winners equal the main decisions in every setting."""
    main = {(x['cell'], x['model'], round(float(x['r']), 3), x['labour']): x['winner']
            for x in csv.DictReader(open(RES / 'main_decisions.csv', encoding='utf-8-sig'))}
    bad = [x for x in rows if main[x['cell'], x['model'], x['r'], x['labour']] != x['winner_common']]
    assert not bad, bad[:3]
    return len(rows)


def data_tables(need_jiang_runs=True):
    d = {'main': load(RES / 'main_fleets.csv'), 'tier_speeds': load(RES / 'tier_speeds_fleets.csv'), 'tier_speeds_jiang': {}}
    p = RES / 'tier_speeds_jiang_fleets.csv'
    if p.exists():
        d['tier_speeds_jiang'] = load(p)
    assert d['tier_speeds_jiang'] or not need_jiang_runs, 'tier_speeds_jiang counts missing (run report_studies study_fleets on tier_speeds_jiang first)'
    return d


def summary(rows, cells, title):
    fmt = lambda g, k: ', '.join('%s %d' % kv for kv in Counter(x[k] for x in g).most_common())
    L = ['## ' + title, '', '| condition | common speeds | tier speeds (mixes 12/5) | tier speeds (mixes 12/6) | changed (pess / opt) | changed, shift staffing | search-dependent (tier) | max regret |',
         '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for cell in cells:
        g = [x for x in rows if x['cell'] == cell]
        L.append('| %s | %s | %s | %s | %d / %d | %d / %d | %d | %.2f%% |' % (
            cell, fmt(g, 'winner_common'), fmt(g, 'winner_tier'), fmt(g, 'winner_tier_mix_opt'),
            sum(x['winner_tier'] != x['winner_common'] for x in g), sum(x['winner_tier_mix_opt'] != x['winner_common'] for x in g),
            sum(x['winner_tier'] != x['winner_common'] for x in g if x['labour'] == 'shift_h'),
            sum(x['winner_tier_mix_opt'] != x['winner_common'] for x in g if x['labour'] == 'shift_h'),
            sum(x['status_tier'] == 'search-dependent' for x in g), 100 * max(x['regret_common_winner'] or 0 for x in g)))
    n = len(rows)
    L += ['', '- all: changed %d / %d (pessimistic), %d (optimistic); shift staffing %d / %d (pessimistic), %d (optimistic)' % (
        sum(x['winner_tier'] != x['winner_common'] for x in rows), n, sum(x['winner_tier_mix_opt'] != x['winner_common'] for x in rows),
        sum(x['winner_tier'] != x['winner_common'] for x in rows if x['labour'] == 'shift_h'), n // 4,
        sum(x['winner_tier_mix_opt'] != x['winner_common'] for x in rows if x['labour'] == 'shift_h'))]
    for f in ('300', '325'):
        L.append('- %s t cheapest: %d (pessimistic), %d (optimistic), %d (common)' % (
            f, sum(x['winner_tier'] == f for x in rows), sum(x['winner_tier_mix_opt'] == f for x in rows), sum(x['winner_common'] == f for x in rows)))
    L.append('- winner couples at most one block in ten: %d / %d (pessimistic), %d (optimistic); largest share %.1f%% / %.1f%%' % (
        sum(x['coop_tier'] <= 0.10 for x in rows), n, sum(x['coop_tier_opt'] <= 0.10 for x in rows),
        100 * max(x['coop_tier'] for x in rows), 100 * max(x['coop_tier_opt'] for x in rows)))
    return L


def main():
    data = data_tables()
    rows = analyse(data, CELLS)
    print('common-speed winners equal main_decisions in', check_common(rows), 'settings')
    write(RES / 'tier_speeds_decisions.csv', rows)
    L = ['# Tier-specific speeds (report_tier_speeds.py)', '', '## Counts K* (common 12/6 -> tier speeds, pessimistic end)', '',
         '| condition | ' + ' | '.join(FAMS) + ' |', '| --- |' + ' --- |' * len(FAMS)]
    for cell in CELLS:
        cells_txt = []
        for f in FAMS:
            st, _, bound = source(cell, f)
            a, b = data['main'].get((cell, f)), data[st].get((cell, f))
            cells_txt.append('%s -> %s%s' % (a['K'] if a else '-', b['K'] if b else '-', ' (bound)' if bound else '' if st != 'main' else ' (main study)'))
        L.append('| %s | %s |' % (cell, ' | '.join(cells_txt)))
    L += [''] + summary(rows, CELLS, 'Eleven reference fleets')
    (RES / 'tier_speeds_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def check_rohcha_liu():
    data = data_tables(need_jiang_runs=False)
    cells = CELLS[2:]
    rows = analyse(data, cells)
    print('common-speed winners equal main_decisions in', check_common(rows), 'settings (Roh-Cha and Liu masses)')
    print('\n'.join(summary(rows, cells, 'Roh-Cha and Liu masses, eleven reference fleets')))


def selfcheck():
    v = lambda K, coop=0.0: dict(K=K, crew_veh_h=0.0, crew_team_h=0.0, after_h=0.0, coop=coop)
    assert source('jiang_short_baseline', 'MX1') == ('tier_speeds_jiang', 550, False) and source('liu_short_baseline', 'MX1') == ('tier_speeds', 425, False)
    assert source('liu_massdep_baseline', 'MX1') == ('main', None, True) and source('rohcha_massdep_baseline', '425') == ('main', None, True)
    assert source('liu_massdep_baseline', '500') == ('tier_speeds', None, False) and source('jiang_massdep_baseline', '425') == ('tier_speeds_jiang', None, False)
    assert source('rohcha_short_baseline', '325') == ('main', None, False) and source('rohcha_short_baseline', 'MX2') == ('tier_speeds', 550, False)
    cell = 'jiang_short_baseline'
    data = {'main': {(cell, f): v(5) for f in FAMS}, 'tier_speeds': {(cell, f): v(6) for f in ('380', '550', 'MX2')},
            'tier_speeds_jiang': {(cell, '425'): v(7), (cell, '500'): v(8), (cell, 'MX1'): v(9)}}
    common, pess, opt = sets(cell, data)
    assert pess['425'][0]['K'] == 7 and pess['MX1'] == (data['tier_speeds_jiang'][cell, 'MX1'], 550) and pess['270'][0]['K'] == 5
    assert opt['MX1'] == (data['main'][cell, 'MX1'], None) and opt['380'][0]['K'] == 6 and len(common) == 11
    _, pess_l, _ = sets(cell, data, ('270', '300', 'MX2'))
    assert sorted(pess_l) == ['270', '300', 'MX2']
    P = C.proxy(('affine',))
    c = cost(cell, {'MX1': (v(9), 550)}, P, 10, 'shift_h')['MX1']
    assert abs(c - (10 * P([550] + [270] * 8) + 64 * 9)) < 1e-9
    w, _, _ = decide(cell, pess, P, 12.4, 'shift_h')        # every main-study family at 5 beats the slower tiers
    assert pess[w][0]['K'] == 5, w
    print('report_tier_speeds self-check passed')


if __name__ == '__main__':
    {'selfcheck': selfcheck, 'check-rohcha-liu': check_rohcha_liu}.get(sys.argv[1] if len(sys.argv) > 1 else '', main)()
