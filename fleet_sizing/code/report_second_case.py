"""Second case (published data of Liu et al. 2022, main specification):
tables from results/second_case_fleets.csv (analyse_study) and results/second_case_replay.json (schedule_replay, 600-min shift).

  additions: n* = K* - 5 per workload k, coupling rule and added type X; '—' = target not met within
             the scan (up to K_S + 4); marks: † a day with after-shift transporter time above 5 % of the
             available time (old rule), * target met only with work after the 10-h shift (shift-hard rule fails)
  scratch:   k = 6 and 8, flexible coupling, 11 fleet types: K*, total capacity, capital proxy (affine price
             curve, VAT removed), shift staffing 4 x 10 h x K, and the cheapest type at r = 5.1, 12.4, 30
Old values (manuscript Table 5, mean on-time target only, 5 weeks, published distance table) are shown
for comparison.

  python report_second_case.py      -> results/second_case_summary.md, results/second_case_additions.csv, results/second_case_scratch.csv
"""
import csv
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
OLD = {  # manuscript Table 5 (current text): (k, rule) -> {X: n*}; None = not reached; † kept as text
    (1, 'nocoup'): dict.fromkeys((250, 270, 380, 420), '0'), (1, 'flex'): dict.fromkeys((250, 270, 380, 420), '0'),
    (2, 'nocoup'): dict.fromkeys((250, 270, 380, 420), '0'), (2, 'flex'): dict.fromkeys((250, 270, 380, 420), '0'),
    (4, 'nocoup'): {250: '—', 270: '—', 380: '1†', 420: '1'}, (4, 'flex'): dict.fromkeys((250, 270, 380, 420), '0†'),
    (6, 'nocoup'): {250: '—', 270: '—', 380: '—', 420: '1†'}, (6, 'flex'): dict.fromkeys((250, 270, 380, 420), '1†'),
    (8, 'nocoup'): {250: '—', 270: '—', 380: '—', 420: '2†'}, (8, 'flex'): {250: '4†', 270: '4†', 380: '3†', 420: '2†'},
}
TYPES = ('200', '250', '270', '300', '325', '380', '425', '500', '550', 'MX1', 'MX2')


def caps(fam, K):
    if fam.startswith('MX'):
        h = int(fam[-1])
        return [550] * h + [270] * (K - h)
    return [int(fam)] * K


def main():
    fl = {r['series']: r for r in csv.DictReader(open(RES / 'second_case_fleets.csv', encoding='utf-8-sig'))}
    rp = json.loads((RES / 'second_case_replay.json').read_text(encoding='utf8'))
    pr = json.loads((RES / 'price_curve.json').read_text(encoding='utf8'))['curves_ex_vat']['affine']
    price = lambda q: pr['F'] + pr['v'] * q
    lines = ['# Second case (Liu 2022 Waigaoqiao data): main results', '',
             'Specification: 30 day instances (6 weeks × 5 days), pooled on-time rate ≥ 95%, delay of every block '
             '≤ 120 min; shortest-path closure distances; the solver (`solver`, PyPy), 5,000 constructions + 786 '
             'iterations, symmetric check at K* − 1. Shift 10 h (600 min).', '',
             '## Additions: the existing fleet (250/270/320/380/420 t) plus n* transporters of type X', '',
             '"—": target not met within the scan limit (K_S + 4); †: on at least one day the after-shift transporter '
             'time exceeds 5% of the available transporter time (old rule); *: target met only when work after the '
             '10-h shift is counted (not met under a hard shift end). In brackets: the current values of manuscript '
             'Table 5 (old specification: mean on-time rate only, 5 weeks, published distance table).', '',
             '| k | rule | 250 t | 270 t | 380 t | 420 t |', '| --- | --- | --- | --- | --- | --- |']
    rows_a = []
    for k in (1, 2, 4, 6, 8):
        for rule, label in (('nocoup', 'no coupling'), ('flex', 'coupling allowed')):
            cells = []
            for X in (250, 270, 380, 420):
                name = 'yard2_k%d_%s_ADD%d' % (k, rule, X)
                r, q = fl[name], rp.get(name)
                if r['K_final'] in ('', 'None'):
                    v = '—'
                    n = None
                else:
                    n = int(r['K_final']) - 5
                    v = str(n) + ('†' if q and q['max_after_share'] > 0.05 else '') + ('*' if q and not q['meets_shift_hard'] else '')
                cells.append('%s (%s)' % (v, OLD[k, rule][X]))
                rows_a.append(dict(k=k, rule=rule, X=X, n_star=n, K_final=r['K_final'], boundary_checked=r['boundary_checked'],
                                   after_share_max=q and round(q['max_after_share'], 4), meets_shift_hard=q and q['meets_shift_hard'],
                                   old=OLD[k, rule][X]))
            lines.append('| %d | %s | %s |' % (k, label, ' | '.join(cells)))
    lines += ['', '## Sizing from scratch (coupling allowed, k = 6, 8)', '',
              'capital proxy = Σ p(Q)/p(270) (affine price curve, VAT removed); shift staffing = 4 persons × 10 h × K; '
              'cost = r × capital proxy + shift staffing (labour hours per day).', '',
              '| k | type | K* | total capacity | capital proxy | shift staffing | needs after-shift work* | '
              'boundary checked |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    rows_s = []
    for k in (6, 8):
        costs = {}
        for t in TYPES:
            name = 'yard2_k%d_flex_%s' % (k, t if t.startswith('MX') else 'T' + t)
            r, q = fl[name], rp.get(name)
            if r['K_final'] in ('', 'None'):
                lines.append('| %d | %s | — | | | | | |' % (k, t))
                continue
            K = int(r['K_final'])
            cp = sum(price(c) for c in caps(t, K)) / price(270)
            costs[t] = (cp, 40 * K)
            lines.append('| %d | %s | %d | %d t | %.2f | %d | %s | %s |' % (k, t, K, sum(caps(t, K)), cp, 40 * K,
                                                                        'yes' if q and not q['meets_shift_hard'] else 'no',
                                                                        'yes' if r['boundary_checked'] == 'True' else 'no'))
            rows_s.append(dict(k=k, type=t, K=K, capacity=sum(caps(t, K)), capital_proxy=round(cp, 3), shift_h=40 * K,
                               needs_after_shift=q and not q['meets_shift_hard'], boundary_checked=r['boundary_checked']))
        best = []
        for rv in (5.1, round(math.sqrt(5.1 * 30), 1), 30.0):
            c = {t: rv * cp + sh for t, (cp, sh) in costs.items()}
            w = min(c, key=c.get)
            srt = sorted(c.values())
            best.append('r = %s: %s (lead over the runner-up %.1f%%)' % (rv, w, 100 * (srt[1] / srt[0] - 1)))
        lines += ['', '- k = %d cheapest: %s; fewest transporters: %s; smallest total capacity: %s' % (
            k, '; '.join(best), ', '.join(sorted(t for t in costs if costs[t][1] == min(v[1] for v in costs.values()))),
            min(costs, key=lambda t: sum(caps(t, costs[t][1] // 40)))), '']
    handling = [v for v in rp.values() if v]
    lines += ['## Handling variability (at K*, 20 scenarios per selected schedule)', '',
              '- nominal on-time rate %.1f–%.1f%%, perturbed %.1f–%.1f%%; share of (instance, scenario) pairs with a '
              'delay above 120 min %.1f–%.1f%% (%d qualifying series).'
              % (100 * min(v['replay_on_nominal'] for v in handling), 100 * max(v['replay_on_nominal'] for v in handling),
                 100 * min(v['replay_on_pert'] for v in handling), 100 * max(v['replay_on_pert'] for v in handling),
                 100 * min(v['replay_share_over'] for v in handling), 100 * max(v['replay_share_over'] for v in handling), len(handling)),
              '- series that still meet the target under a hard shift end: %d / %d.' % (sum(v['meets_shift_hard'] for v in handling), len(handling))]
    (RES / 'second_case_summary.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    for fn, rows in (('second_case_additions.csv', rows_a), ('second_case_scratch.csv', rows_s)):
        with open(RES / fn, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
