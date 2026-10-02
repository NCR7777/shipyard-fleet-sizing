"""425 t, 500 t and the mass-matched mixes under handling x1.5 and x2.0 (directory `candidates_handling`).

The one-factor sensitivity study compared five fleet types; the slow-speed extension (directory `candidates_speed`) added the
main-grid winners (425 t, 500 t, mixes) only at the slow speeds. This applies the same preparation (families, mix
rule N = min(K550 - 1, ceil(K550 h)), seed offset, hi_limit 40) to the two handling levels. Conditions without a
550 t count (unattainable) are skipped, as in the slow-speed extension.

  python code/candidates_handling.py candidates_handling
  pypy code/supervise.py candidates_handling fleet_scan_studies.py <workers>
  python code/analyse_study.py candidates_handling                  # confirm_report.py slow-handling reads every candidates_*_fleets.csv
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'supplementary'))
import confirm_run as S

FACTORS = ['hand1.5', 'hand2.0']
_design = S.design


def design(name):
    p = _design(name)
    if name == 'slow_handling.json':
        p = dict(p, part_b=dict(p['part_b'], factors=FACTORS))
    return p


if __name__ == '__main__':
    S.design = design
    S.prepare_candidates(sys.argv[1])
