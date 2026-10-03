"""Independent checks of fluid_check.py and of three statements of Section 5.4 (on-time targets).

1. w_bar of every covering fleet equals w_single_min of the vehicle-time decomposition (results/vehicle_time_series.csv).
2. Single-carry share at r = 30 on the main grid, outside the heavy-tail profile (results/main_decisions.csv).
3. The 9,450 fluid and simulated cost ratios of results/fluid_pairs_main.csv, recomputed with separate code.
4. Price-free test: for homogeneous fleets the simulated ratio is (K_lo / K_hi) (c_lo / c_hi) and the fluid ratio is
   (occupancy factor) (c_lo / c_hi), so the 45 cost settings of a fleet pair share the price factor; the test without
   it correlates the occupancy factor with K_lo / K_hi over the fleet pairs.
5. The 42 contending fleets at K* and K* - 1: on-time share 98% or more at K*; fleets with runs at K* - 1; days without
   a schedule within the cap at K* - 1; pooled on-time share of the best run per day at K* - 1.

  python fluid_verify.py        -> results/fluid_verify.json   (after fluid_check.py)
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(HERE))
import cost_decisions as RC  # noqa: E402

COVER = {'jiang': 500, 'lightskew': 500, 'uniform': 500, 'rohcha': 550, 'liu': 425}
out = {}
f = pd.read_csv(RES / 'main_fleets.csv')
f = f[f.K_final.notna()]
row = {(c, str(fa)): r for c, fa, r in zip(f.cell, f.family, f.itertuples())}
wbar = lambda r: r.crew_veh_h / 4 * 60 / 97

# 1
vt = pd.read_csv(RES / 'vehicle_time_series.csv')
vt = {(c, str(fa)): w for c, fa, w in zip(vt.cell, vt.family, vt.w_single_min)}
d1 = [abs(wbar(row[c, str(COVER[c.split('_')[0]])]) - vt[c, str(COVER[c.split('_')[0]])]) for c in sorted(set(f.cell))
      if c.split('_')[0] in COVER]
out['w_bar_vs_vt_decomposition'] = dict(covering_fleets=len(d1), max_abs_diff_min=max(d1))

# 2
d = pd.read_csv(RES / 'main_decisions.csv')
d30 = d[(d.r.round(3) == 30.0) & (~d.cell.str.startswith('extraheavy'))]
sc = [row[c, str(w)].coop_share <= 0.1 + 1e-12 for c, w in zip(d30.cell, d30.winner)]
out['single_carry_at_r30_outside_heavy_tail'] = dict(single=int(sum(sc)), decisions=len(sc), pct=round(100 * float(np.mean(sc)), 2))

# 3 and 4
pairs = pd.read_csv(RES / 'fluid_pairs_main.csv')
tasks = pd.read_csv(RES / 'runs_compact' / 'tasks_main.csv')
P = {RC.mname(m): RC.proxy(m) for m in RC.MAIN_MODELS}
worst_f = worst_s = 0.0
per_pair = []
for (cell, lo), g in pairs.groupby(['cell', 'lo']):
    hi = COVER[cell.split('_')[0]]
    m = tasks[tasks.cell == cell].mass_t.to_numpy(float)
    rl, rh = row[cell, str(lo)], row[cell, str(hi)]
    w = wbar(rh)
    factor = sum(w if x <= lo else math.ceil(x / lo) * (w + 10.0) for x in m) / (w * len(m))
    for x in g.itertuples():
        pp = P[x.model]
        fluid = (x.r * pp([lo]) + 64) / (x.r * pp([hi]) + 64) * factor
        sim = ((x.r * pp(RC.caps(cell, str(lo), int(rl.K_final))) + 64 * rl.K_final) /
               (x.r * pp(RC.caps(cell, str(hi), int(rh.K_final))) + 64 * rh.K_final))
        worst_f, worst_s = max(worst_f, abs(fluid - x.fluid)), max(worst_s, abs(sim - x.sim))
    per_pair.append((factor, rl.K_final / rh.K_final))
fac, kr = np.array(per_pair).T
out['recomputed_pairs'] = dict(comparisons=len(pairs), max_abs_diff_fluid=worst_f, max_abs_diff_sim=worst_s)
out['price_free_test'] = dict(fleet_pairs=len(fac), pearson=round(float(np.corrcoef(fac, kr)[0, 1]), 4),
                              spearman=round(float(spearmanr(fac, kr).correlation), 4),
                              median_count_ratio_over_factor_minus1_pct=round(100 * float(np.median(kr / fac - 1)), 2))

# 5
service_design = json.loads((STUDY_ROOT / 'supplementary_outage' / 'design' / 'service_level.json').read_text(encoding='utf8'))
runs = {s: pd.read_csv(RES / 'runs_compact' / ('%s.csv' % s)) for s in ('main', 'delay_cap')}
fls = {s: pd.read_csv(RES / ('%s_fleets.csv' % s)).set_index('series') for s in ('main', 'delay_cap')}
need98 = math.ceil(0.98 * 2910 - 1e-9)
ge98, short, km1, no_cap, share = 0, [], [], 0, []
for it in service_design['series']:
    r = runs[it['study']][runs[it['study']].series == it['series']]
    K = int(fls[it['study']].loc[it['series'], 'K_final'])
    capped = lambda k: r[(r.K <= k) & (r.status == 'OK') & (r.n_over == 0)].groupby('seed').on_time.max()
    on = int(capped(K).sum())
    ge98 += on >= need98
    if on < need98:
        short.append(need98 - on)
    if K - 1 in set(r.K):
        km1.append(it['series'])
        no_cap += len(capped(K - 1)) < 30
        share.append(float(r[(r.K <= K - 1) & (r.status == 'OK')].groupby('seed').on_time.max().sum() / 2910))
out['contending_fleets'] = dict(fleets=len(service_design['series']), at_Kstar_on_time_98pct_or_more=int(ge98),
                                shortfalls_of_the_others_blocks=sorted(short), with_runs_at_Kstar_minus1=len(km1),
                                Kstar_minus1_day_without_capped_schedule=int(no_cap),
                                Kstar_minus1_best_run_on_time_pct=[round(100 * min(share), 1), round(100 * max(share), 1)])

(RES / 'fluid_verify.json').write_text(json.dumps(out, indent=1) + '\n', encoding='utf8')
print(json.dumps(out, indent=1))
