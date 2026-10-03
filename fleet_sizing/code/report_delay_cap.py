"""Report of the delay-cap study (directory `delay_cap`): the delay-cap axis; run after that study finishes.

Counts: analyse_study on the delay-cap study (levels inf, 480, 240, 120, 60, 30 min; conditions with the Jiang, uniform
and Liu mass scenarios x short handling x baseline due dates). At 120 min the series that coincide with the main
study take their main-study counts; the two-tier mixes of the delay-cap study keep their own.
Outputs per level and cell:
  - K* of every family, the smallest count and which families reach it (four-transporter status);
  - the cheapest qualifying fleet and its daily cost (affine price curve, shift staffing, the nine calibrated r).
Four-transporter rule: if some family meets the uncapped target (level inf) with four transporters on the
30 instances, report for those fleets, from the best schedule per instance at count <= 4 (most on-time blocks, then
smaller maximum delay): the largest delay, the number of blocks more than 4 h late and the after-shift
transporter-hours per day; otherwise report the smallest uncapped count X and its families.

  python report_delay_cap.py      -> results/delay_cap_fleets.csv (analyse_study), delay_cap_axis.csv, delay_cap_summary.md
"""
import csv
import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(HERE))
import cost_decisions as C                                      # noqa: E402

LEVELS = ['inf', '480', '240', '120', '60', '30']


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def counts():
    import analyse_study as A
    rows = A.analyse(STUDY_ROOT / 'delay_cap')
    specs = {sp['name']: sp for sp in json.loads((STUDY_ROOT / 'delay_cap' / 'series.json').read_text(encoding='utf8'))}
    out = {}
    for r in rows:
        sp = specs[r['series']]
        out[sp['level'], sp['cell'], sp['family']] = dict(K=r['K_final'], series=r['series'], boundary=r['boundary_checked'])
    main_counts = {(r['cell'], r['family']): int(r['K_final']) for r in rcsv(RES / 'main_fleets.csv')}
    for cell in {c for _, c, _ in out}:     # at 120 min only the two-tier mixes were run; the rest is the main study
        for (c, fam), k in main_counts.items():
            if c == cell:
                out['120', cell, fam] = dict(K=k, series='main:%s_%s' % (cell, fam), boundary=True)
    return rows, out


def four_detail(series_names):
    """Four-transporter rule: statistics of the best uncapped schedules at count <= 4 (one per instance)."""
    import schedule_replay as RP
    for sub in ('common', 'search'):
        q = str(RP.SOLVER / sub)
        if q not in sys.path:
            sys.path.insert(0, q)
    from core import evaluate
    specs = {sp['name']: sp for sp in json.loads((STUDY_ROOT / 'delay_cap' / 'series.json').read_text(encoding='utf8'))}
    out = {}
    for name in series_names:
        sp = specs[name]
        late_max, over4h, after, on = 0, 0, 0.0, 0
        for s in range(101, 131):
            best = None
            for p in (STUDY_ROOT / 'delay_cap' / 'runs' / name).glob('K*_s%d_j*.json' % s):
                k = int(p.name.split('_')[0][1:])
                if k > 4:
                    continue
                r = json.loads(p.read_text(encoding='utf8'))
                if r['status'] == 'OK':
                    key = (-r['on_time'], r['max_tard'], k, r['job']['j'])
                    if best is None or key < best[0]:
                        best = (key, r, k)
            assert best, (name, s)
            _, r, k = best
            inst = RP.instance(STUDY_ROOT / 'delay_cap', sp, k, s)
            ev = evaluate(inst, r['order'], {int(i): tuple(v) for i, v in r['team'].items()}, 0, detail=True)
            late = [ev['comp'][i] - inst.due[i] for i in range(inst.n)]
            last = [max((ev['comp'][i] for i in q), default=0) for q in ev['seqs']]
            on += sum(x <= 0 for x in late)
            late_max = max(late_max, max(late))
            over4h += sum(x > 4 * 3600 for x in late)
            after += sum(max(0, c - 16 * 3600) for c in last) / 3600
        out[name] = dict(on_time=on, max_delay_min=round(late_max / 60), blocks_over_4h=over4h, after_shift_h_per_day=round(after / 30, 2))
    return out


def label(cell, fam, K):
    """Fleet composition as priced, e.g. '1x500 + 4x270 t' (MX1 with a substituted heavy member equals L270_H500x1)."""
    from collections import Counter
    return ' + '.join('%dx%d' % (n, q) for q, n in sorted(Counter(C.caps(cell, fam, K)).items(), reverse=True)) + ' t'


def main():
    rows, K = counts()
    with open(RES / 'delay_cap_fleets.csv', 'w', encoding='utf-8-sig', newline='') as f:
        keys = []
        for r in rows:                              # rows without a count lack the pricing columns
            keys += [k for k in r if k not in keys]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    cells = sorted({c for _, c, _ in K})
    rs = C.main_r()
    P = C.proxy(('affine',))
    axis, L = [], ['# Delay-cap axis (30 instances; report_delay_cap.py)', '']
    for lev in LEVELS:
        for cell in cells:
            fams = {f: v for (l, c, f), v in K.items() if l == lev and c == cell and v['K'] not in (None, '', 'None')}
            if not fams:
                continue
            kmin = min(int(v['K']) for v in fams.values())
            for r in rs:
                cost = {f: (r * P(C.caps(cell, f, int(v['K']))) + 64 * int(v['K']), not str(v['series']).startswith('main:'))
                        for f, v in fams.items()}         # at a cost tie the main-study run is taken (as in grid)
                wn = min(cost, key=cost.get)
                axis.append(dict(level=lev, cell=cell, r=round(r, 3), winner=wn, fleet=label(cell, wn, int(fams[wn]['K'])),
                                 K_winner=int(fams[wn]['K']), cost=round(cost[wn][0], 2),
                                 K_min=kmin, families_at_min=' '.join(sorted(f for f, v in fams.items() if int(v['K']) == kmin))))
    with open(RES / 'delay_cap_axis.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(axis[0]))
        w.writeheader()
        w.writerows(axis)
    L += ['## Smallest count and cheapest fleet (affine price, shift staffing, r = %.1f)' % rs[4], '',
          '| T_max | condition | smallest K* (families) | cheapest fleet (K*) | daily cost |', '| --- | --- | --- | --- | --- |']
    for a in axis:
        if abs(a['r'] - round(rs[4], 3)) < 1e-9:
            L.append('| %s | %s | %d (%s) | %s (%d) | %.1f |' % (a['level'], a['cell'], a['K_min'], a['families_at_min'], a['fleet'],
                                                             a['K_winner'], a['cost']))
    inf4 = [v['series'] for (l, c, f), v in K.items() if l == 'inf' and v['K'] not in (None, '', 'None') and int(v['K']) <= 4]
    L += ['', '## Four transporters under the uncapped target (30 instances)', '']
    if inf4:
        det = four_detail(sorted(inf4))
        L.append('Four transporters meet the uncapped target in %d series:' % len(inf4))
        L += ['- %s: on time %d of 2,910; largest delay %d min; %d blocks more than 4 h late; %.2f after-shift transporter-hours per day'
              % (n, d['on_time'], d['max_delay_min'], d['blocks_over_4h'], d['after_shift_h_per_day']) for n, d in det.items()]
        (RES / 'delay_cap_four_transporters.json').write_text(json.dumps(det, indent=1) + '\n', encoding='utf8')
    else:
        kinf = [(int(v['K']), f, c) for (l, c, f), v in K.items() if l == 'inf' and v['K'] not in (None, '', 'None')]
        x = min(k for k, _, _ in kinf)
        L.append('No fleet meets the uncapped target with four transporters on 30 instances; the smallest uncapped count is %d (%s).'
                 % (x, ', '.join('%s %s' % (c, f) for k, f, c in sorted(kinf) if k == x)))
    (RES / 'delay_cap_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def _row(r, src):
    return dict(K=int(r['K_final']), crew_veh_h=float(r['crew_veh_h']), crew_team_h=float(r['crew_team_h']),
                after_h=float(r['after_h'] or 0), coop=float(r['coop_share'] or 0), src=src)


def fleet_tables():
    """level -> cell -> family -> fleet row; at 120 min the reference families come from the main study (the
    delay-cap study ran only the mixes at that level)."""
    out = {}
    for r in rcsv(RES / 'delay_cap_fleets.csv'):
        if r['K_final'] not in (None, '', 'None'):
            out.setdefault(r['series'].split('_')[0][1:], {}).setdefault(r['cell'], {})[r['family']] = _row(r, 'delay_cap')
    for r in rcsv(RES / 'main_fleets.csv'):
        if r['cell'] in out['120'] and r['K_final'] not in (None, '', 'None'):
            out['120'][r['cell']].setdefault(r['family'], _row(r, 'main'))
    return out


def grid():
    """The delay-cap axis on the main grid (5 price models x 9 r x 4 labour measures): cheapest fleet, its coupled share
    and its cost relative to the uncapped cheapest fleet. Fleets with the same priced capacities are the same fleet
    (MX1/MX2 with substituted heavy members equal L270_H<sub>x1/x2); at a cost tie the main-study run is taken."""
    T = fleet_tables()
    rows = []
    for m in C.MAIN_MODELS:
        P = C.proxy(m)
        for cell in sorted(T['inf']):
            for r in C.main_r():
                for lab in C.LAB4:
                    best = {}
                    for lev in LEVELS:
                        fams = T[lev][cell]
                        cost = {f: (r * P(C.caps(cell, f, v['K'])) + C.labour(v, lab, v['K']), v['src'] != 'main') for f, v in fams.items()}
                        w = min(cost, key=cost.get)
                        best[lev] = (w, cost[w][0], fams[w])
                    for lev in LEVELS:
                        w, c, v = best[lev]
                        rows.append(dict(level=lev, cell=cell, model=C.mname(m), r=round(r, 3), labour=lab, winner=w, K=v['K'],
                                         fleet=' '.join(map(str, sorted(C.caps(cell, w, v['K'])))), coop=v['coop'], cost=c,
                                         cost_vs_inf=c / best['inf'][1] - 1))
    with open(RES / 'delay_cap_grid.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    L = ['# Delay-cap axis on the main grid (180 settings per condition and cap)', '',
         '| condition | cap | cheapest fleets (settings) | coupled share median [min, max] | fleet differs from uncapped | cost vs uncapped median [min, max] |',
         '| --- | --- | --- | --- | --- | --- |']
    for cell in sorted(T['inf']):
        inf = {(x['model'], x['r'], x['labour']): x['fleet'] for x in rows if x['cell'] == cell and x['level'] == 'inf'}
        for lev in LEVELS:
            g = [x for x in rows if x['cell'] == cell and x['level'] == lev]
            cnt = {}
            for x in g:
                cnt[x['winner']] = cnt.get(x['winner'], 0) + 1
            co, cv = [x['coop'] for x in g], [x['cost_vs_inf'] for x in g]
            L.append('| %s | %s | %s | %.1f%% [%.1f, %.1f] | %d | %.2f%% [%.2f, %.2f] |' % (
                cell, lev, ', '.join('%s %d' % kv for kv in sorted(cnt.items(), key=lambda kv: -kv[1])),
                100 * st.median(co), 100 * min(co), 100 * max(co),
                sum(x['fleet'] != inf[x['model'], x['r'], x['labour']] for x in g),
                100 * st.median(cv), 100 * min(cv), 100 * max(cv)))
    (RES / 'delay_cap_grid_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))
    return rows


def late_blocks():
    """Series that qualify uncapped with fewer transporters than under the 120-min cap: in the best uncapped schedule per
    instance at that count (most on-time blocks, then smaller maximum delay), the blocks more than 4 h late, how many of
    them are coupled moves, and the coupled share of all blocks."""
    import schedule_replay as RP
    for sub in ('common', 'search'):
        q = str(RP.SOLVER / sub)
        if q not in sys.path:
            sys.path.insert(0, q)
    from core import evaluate
    T = fleet_tables()
    specs = {sp['name']: sp for sp in json.loads((STUDY_ROOT / 'delay_cap' / 'series.json').read_text(encoding='utf8'))}
    out = []
    for cell in sorted(T['inf']):
        for fam, v in sorted(T['inf'][cell].items()):
            k120 = T['120'][cell].get(fam, {}).get('K')
            if k120 is None or k120 <= v['K']:
                continue
            name = 'Tinf_%s_%s' % (cell, fam)
            sp = specs[name]
            st_ = dict(on=0, n=0, coupled=0, late4=0, late4_coupled=0, late2=0, max_s=0)
            for s in range(101, 131):
                best = None
                for p in (STUDY_ROOT / 'delay_cap' / 'runs' / name).glob('K*_s%d_j*.json' % s):
                    k = int(p.name.split('_')[0][1:])
                    r = json.loads(p.read_text(encoding='utf8')) if k <= v['K'] else None
                    if r and r['status'] == 'OK':
                        key = (-r['on_time'], r['max_tard'], k, r['job']['j'])
                        if best is None or key < best[0]:
                            best = (key, r, k)
                _, r, k = best
                inst = RP.instance(STUDY_ROOT / 'delay_cap', sp, k, s)
                team = {int(i): tuple(x) for i, x in r['team'].items()}
                ev = evaluate(inst, r['order'], team, 0, detail=True)
                for i in range(inst.n):
                    late = ev['comp'][i] - inst.due[i]
                    cp = len(team[i]) > 1
                    st_['n'] += 1
                    st_['on'] += late <= 0
                    st_['coupled'] += cp
                    st_['late2'] += late > 2 * 3600
                    st_['late4'] += late > 4 * 3600
                    st_['late4_coupled'] += late > 4 * 3600 and cp
                    st_['max_s'] = max(st_['max_s'], late)
            out.append(dict(cell=cell, family=fam, K_uncapped=v['K'], K_120=k120, on_time=st_['on'], coupled_share=st_['coupled'] / st_['n'],
                            max_delay_h=round(st_['max_s'] / 3600, 1), late_over_2h=st_['late2'], late_over_4h=st_['late4'],
                            late_over_4h_coupled=st_['late4_coupled']))
    with open(RES / 'delay_cap_late_blocks.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for x in out:
        print(x)
    return out


if __name__ == '__main__':
    {'grid': grid, 'late': late_blocks}.get(sys.argv[1] if len(sys.argv) > 1 else '', main)()
