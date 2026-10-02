"""Structural screen (supplementary/structural_screen.bounds) of the candidate families added for slow speed and long handling
(directory `candidates_speed`) in the three conditions where every fleet type of the one-factor sensitivity study is unattainable:
can 425 t, 500 t or a light fleet with 500/550 t members meet the target at any K <= 40?

The bound depends on the family only through the largest capacity (a block heavier than it adds delta), so a
fleet whose largest unit is at most 550 t cannot do better than 550 t; the mixes are screened at both ends of
the heavy-member count. The 550 t row reproduces results/sensitivity_precheck.csv.

  python code/screen_candidates.py      -> results/slow_handling_screen_candidates.csv
"""
import csv
import json
import math
import sys
from pathlib import Path

STUDY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDY_ROOT / 'supplementary'))
import structural_screen as P

CELLS = ['speedliu_jiang_massdep_baseline', 'speedliu_rohcha_massdep_baseline', 'hand2.0_rohcha_massdep_baseline']
FAMS = {'425': [425] * 40, '500': [500] * 40, 'L300_H500x2': [500] * 2 + [300] * 38,
        'L300_H550x5': [550] * 5 + [300] * 35, 'L300_H550x30': [550] * 30 + [300] * 10, '550': [550] * 40}


def main():
    specs = {sp['name']: sp for sp in json.loads((STUDY_ROOT / 'sensitivity' / 'series.json').read_text(encoding='utf8'))}
    rows = []
    for cell in CELLS:
        sp = specs[cell + '_T550']
        tmax = sp['tmax_s'] or math.inf
        days = [json.loads((STUDY_ROOT / 'sensitivity' / sp['base'][str(s)]).read_text(encoding='utf8')) for s in sp['seeds']]
        for fam, caps in FAMS.items():
            lbs = [P.bounds(d, caps) for d in days]
            if any(x is None for x in lbs):
                rows.append(dict(cell=cell, family=fam, verdict='structural', surely_late='', surely_over='', allowance=''))
                continue
            n = sum(map(len, lbs))
            late = sum(x > 0 for l in lbs for x in l)
            over = sum(x > tmax for l in lbs for x in l)
            allow = n - math.ceil(0.95 * n - 1e-9)
            rows.append(dict(cell=cell, family=fam, verdict='unattainable' if over or late > allow else 'open',
                             surely_late=late, surely_over=over, allowance=allow))
    with open(STUDY_ROOT / 'results' / 'slow_handling_screen_candidates.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    ref = {r['series']: r for r in csv.DictReader(open(STUDY_ROOT / 'results' / 'sensitivity_precheck.csv', encoding='utf-8-sig'))}
    for r in rows:
        if r['family'] == '550':
            e = ref[r['cell'] + '_T550']
            assert (e['verdict'], int(e['surely_late'])) == (r['verdict'], r['surely_late']), (r, e)
    for r in rows:
        print(r)


if __name__ == '__main__':
    main()
