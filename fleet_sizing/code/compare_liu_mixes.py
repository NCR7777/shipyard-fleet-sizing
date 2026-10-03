"""Liu composition claim under the main and the all-10/5 speed settings.

Condition `liu_short_baseline`. Candidates and counts (fleet tables written by analyse_study.py):
  main (common 12/6 km/h): the 11 reference families from the main study; the expanded two-tier mixes of 300 or
      270 t light and 425 t heavy members (`L300_H425x1`-`x4`, `L270_H425x1`-`x4`) from the delay-cap study at the
      120-min level; the 550 t heavy member of `MX1`/`MX2` priced as 425 t (manuscript rule).
  all-10/5 (conservative for the mixes): expanded mixes and `MX1` from the new tier-speed runs (all members 10/5),
      `MX1` priced with a 425 t heavy member; 380, 425, 500, 550 and `MX2` from the tier-speed study at the
      manufacturer tier speeds, `MX2` priced as 550 t (no substitution); 200, 250, 270, 300, 325 from the main
      study (12/6).
Settings: the 45 of the old grid (alpha 0.6/0.8/1.0 x r 5/10/20/40/85 x shift, per-transporter and per-team crew)
and the main calibrated grid (5 price models x 400 r on [5.1, 30] x 4 labour measures).
Reports whether the 425/300 mixes (and any expanded mix) are cheapest in every setting and the premium range
(best other candidate / best 425-300 mix - 1).

  python compare_liu_mixes.py [main_fleets.csv delay_cap_fleets.csv tier_speeds_fleets.csv]   (defaults in results/)
  python compare_liu_mixes.py selfcheck
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE.parent / 'results'
sys.path.insert(0, str(HERE))
import cost_decisions as C                                     # noqa: E402

CELL = 'liu_short_baseline'
L300 = ['L300_H425x%d' % h for h in (1, 2, 3, 4)]
EXPANDED = L300 + ['L270_H425x%d' % h for h in (1, 2, 3, 4)]
TIER_SPEED_FAMS = ('380', '425', '500', '550', 'MX2')


def caps(fam, K, heavy_mx):
    if fam.startswith('MX'):
        h = int(fam[-1])
        return [heavy_mx] * h + [270] * (K - h)
    return C.caps(CELL, fam, K)


def load(path, prefix='', only=None):
    out = {}
    for r in csv.DictReader(open(path, encoding='utf-8-sig')):
        if r['cell'] != CELL or not r['series'].startswith(prefix) or r.get('K_final') in (None, '', 'None'):
            continue
        if only and r['family'] not in only:
            continue
        out[r['family']] = dict(K=int(r['K_final']), crew_veh_h=float(r['crew_veh_h']), crew_team_h=float(r['crew_team_h']),
                                after_h=float(r['after_h'] or 0))
    return out


def candidates(main_fl, cap_fl, tier_fl, setting):
    """family -> (fleet row, heavy capacity used for MX pricing)."""
    if setting == 'main':
        c = {f: (v, 425) for f, v in main_fl.items()}
        c.update({f: (v, None) for f, v in cap_fl.items() if f in EXPANDED})
    else:
        c = {f: (v, None) for f, v in main_fl.items() if f in ('200', '250', '270', '300', '325')}
        c.update({f: (v, 550 if f == 'MX2' else None) for f, v in tier_fl.items() if f in TIER_SPEED_FAMS})
        c.update({f: (v, 425 if f == 'MX1' else None) for f, v in tier_fl.items() if f in EXPANDED + ['MX1']})
    return c


def compare(cands, models, rs, labs):
    rows = []
    for m in models:
        P = C.proxy(m)
        cap = {f: P(caps(f, v['K'], hv or 550)) for f, (v, hv) in cands.items()}
        for r in rs:
            for lab in labs:
                cost = {f: r * cap[f] + C.labour(v, lab, v['K']) for f, (v, hv) in cands.items()}
                best300 = min((cost[f] for f in L300 if f in cost), default=math.inf)
                bestexp = min((cost[f] for f in EXPANDED if f in cost), default=math.inf)
                other = min(c for f, c in cost.items() if f not in EXPANDED)
                rows.append(dict(model=C.mname(m), r=r, labour=lab, l300_cheapest=best300 <= min(cost.values()) + 1e-9,
                                 expanded_cheapest=bestexp <= min(cost.values()) + 1e-9, premium=other / best300 - 1,
                                 winner=min(cost, key=cost.get)))
    return rows


def summarise(rows):
    return dict(settings=len(rows), l300_cheapest=sum(r['l300_cheapest'] for r in rows),
                expanded_cheapest=sum(r['expanded_cheapest'] for r in rows),
                premium_min_pct=round(100 * min(r['premium'] for r in rows), 1), premium_max_pct=round(100 * max(r['premium'] for r in rows), 1),
                other_winners=sorted({r['winner'] for r in rows if not r['expanded_cheapest']}))


def run(main_fl, cap_fl, tier_fl):
    import numpy as np
    lo, hi = json.loads((RES / 'price_curve.json').read_text(encoding='utf8'))['r_union_main']
    rs_main = [float(x) for x in np.exp(np.linspace(math.log(lo), math.log(hi), 400))]
    out = {}
    for setting in ('main', 'all_10_5'):
        cands = candidates(main_fl, cap_fl, tier_fl, setting)
        out[setting] = dict(candidates=sorted(cands),
                            old45=summarise(compare(cands, C.OLD_MODELS, (5, 10, 20, 40, 85), C.LAB3)),
                            main_grid=summarise(compare(cands, C.MAIN_MODELS, rs_main, C.LAB4)))
    return out


def selfcheck():
    """Synthetic fleets: the 425/300 mix is cheapest by construction in 'main'; in 'all_10_5' its count grows so
    that a homogeneous tier wins at high r."""
    base = dict(crew_veh_h=300.0, crew_team_h=250.0, after_h=0.0)
    main_fl = {f: dict(base, K=k) for f, k in (('200', 12), ('250', 9), ('270', 9), ('300', 8), ('325', 8), ('380', 6), ('425', 5),
                                          ('500', 5), ('550', 5), ('MX1', 7), ('MX2', 6))}
    cap_fl = {f: dict(base, K=4 if f in L300 else 5, crew_veh_h=200.0) for f in EXPANDED}
    tier_fl = dict({f: dict(base, K=k) for f, k in (('380', 7), ('425', 6), ('500', 5), ('550', 5), ('MX2', 7), ('MX1', 8))},
              **{f: dict(base, K=7) for f in EXPANDED})
    out = run(main_fl, cap_fl, tier_fl)
    assert out['main']['old45']['settings'] == 45 and out['main']['old45']['l300_cheapest'] == 45, out['main']['old45']
    assert out['all_10_5']['old45']['l300_cheapest'] < 45, out['all_10_5']['old45']
    assert 'MX1' in out['all_10_5']['candidates'] and '380' in out['all_10_5']['candidates']
    print('self-check passed:', out['main']['old45'], out['all_10_5']['old45'])


if __name__ == '__main__':
    if sys.argv[1:2] == ['selfcheck']:
        selfcheck()
        sys.exit()
    a = sys.argv[1:] or [RES / 'main_fleets.csv', RES / 'delay_cap_fleets.csv', RES / 'tier_speeds_fleets.csv']
    out = run(load(a[0]), load(a[1], prefix='T120_'), load(a[2]))
    (RES / 'liu_mix_compare.json').write_text(json.dumps(out, indent=1) + '\n', encoding='utf8')
    print(json.dumps(out, indent=1))
