"""Fluid-model numbers of the manuscript (Sections 3.3, 5.2 and 5.3), recomputed from the result tables.

Usage:  python code/fluid_check.py [path/to/fleet_sizing]   (default: the fleet_sizing folder above code/)
Needs:  results/main_fleets.csv, results/main_load_rule.csv, results/heavy_share_fleets.csv,
        results/runs_compact/tasks_main.csv, results/runs_compact/tasks_heavy_share.csv, results/price_curve.json,
        code/cost_decisions.py (prices, fleet capacities, labour measures).
Writes: results/fluid_check.json, results/fluid_pairs_main.csv, results/fluid_pairs_heavy_share.csv.

Definitions (as in the manuscript):
  c(Q) = r*pi(Q) + l, pi(Q) = p(Q)/p(270), l = 64 labour-hours (shift labour); delta = 10 min.
  kappa = c(Q_hi)/c(Q_lo) - 1.
  w_bar = mean occupancy per block of the covering (single-carry) fleet = its crew-vehicle hours / 4 / blocks per day
          (equals w_single_min of the vehicle-time decomposition for every covering fleet, because it never waits).
  Fluid cost ratio of a light homogeneous tier Q_lo to the covering tier Q_hi in one condition:
          [c(Q_lo) / c(Q_hi)] * (1/n) * sum_i occ_i / w_bar,   occ_i = w_bar if m_i <= Q_lo, else g_i (w_bar + delta),
          g_i = ceil(m_i / Q_lo) (minimal homogeneous team), over all blocks of the condition's 30 days.
  Simulated cost ratio = C_lo / C_hi with C = r P_X + 64 K* (shift labour, K* from main_fleets).
  Coupling budget h* = kappa / (1 + 2 delta / w_bar);  h = coupled share of occupancy sum_{coupled} w / sum w (w uniform).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent
RES = BASE / 'results'
sys.path.insert(0, str(BASE / 'code'))
import cost_decisions as RC  # noqa: E402

DELTA, ELL = 10.0, 64.0
HOM = [200, 250, 270, 300, 325, 380, 425, 500, 550]
RS = RC.main_r()
OUT = {}


def wbar(row, n_per_day=97):
    return row.crew_veh_h / 4 * 60 / n_per_day


def cover(masses):
    mx = masses.max()
    return next((q for q in HOM if q >= mx), None)


def occ_factor(m, q, w):
    g = np.ceil(m / q)
    occ = np.where(m <= q, w, g * (w + DELTA))
    return occ.sum() / (w * len(m)), float(np.where(m > q, w, 0).sum() / (w * len(m)))


def fleet_cost(cell, fam, K, P, r):
    return r * P(RC.caps(cell, fam, int(K))) + ELL * K


# ---------------------------------------------------------------- Section 3.3: kappa ranges
pw = RC.proxy(('power', 0.84))
def kappa(hi, lo, r):
    return (r * pw([hi]) + ELL) / (r * pw([lo]) + ELL) - 1
OUT['kappa_425_vs_270_pct'] = [round(100 * kappa(425, 270, r), 2) for r in (RS[0], RS[-1])]
OUT['kappa_550_vs_300_pct'] = [round(100 * kappa(550, 300, r), 2) for r in (RS[0], RS[-1])]
OUT['r_range'] = [round(RS[0], 3), round(RS[-1], 3)]

# ---------------------------------------------------------------- Section 5.2: fluid vs simulated cost ratios (main study)
f = pd.read_csv(RES / 'main_fleets.csv')
f = f[f.K_final.notna()].copy()
tasks = pd.read_csv(RES / 'runs_compact' / 'tasks_main.csv')
mass = {c: g.mass_t.to_numpy(float) for c, g in tasks.groupby('cell')}
rows = []
wcov = {}
for cell, g in f.groupby('cell'):
    qc = cover(mass[cell])
    if qc is None:          # heavy-tail profile: no single-carry tier
        continue
    gi = g.set_index('family')
    hi = gi.loc[str(qc)]
    w = wbar(hi)
    wcov[cell] = w
    for q in HOM:
        if q >= qc or str(q) not in gi.index:
            continue
        lo = gi.loc[str(q)]
        fac, h = occ_factor(mass[cell], q, w)
        for mod in RC.MAIN_MODELS:
            P = RC.proxy(mod)
            for r in RS:
                fluid = (r * P([q]) + ELL) / (r * P([qc]) + ELL) * fac
                sim = fleet_cost(cell, str(q), lo.K_final, P, r) / fleet_cost(cell, str(qc), hi.K_final, P, r)
                rows.append(dict(cell=cell, lo=q, hi=qc, model=RC.mname(mod), r=r, h=h, fluid=fluid, sim=sim))
d = pd.DataFrame(rows)
d.to_csv(RES / 'fluid_pairs_main.csv', index=False)
sep = (d.sim - 1).abs() >= 0.10
ok = np.sign(d.fluid - 1) == np.sign(d.sim - 1)
OUT['main_fluid'] = dict(
    pairs=len(d), fleet_pairs=int(d.groupby(['cell', 'lo']).ngroups), conditions=int(d.cell.nunique()),
    pearson=round(float(np.corrcoef(d.fluid, d.sim)[0, 1]), 4),
    median_understatement_pct=round(100 * float(((d.sim - d.fluid) / d.sim).median()), 2),
    median_sim_over_fluid_minus1_pct=round(100 * float((d.sim / d.fluid - 1).median()), 2),
    share_separated_10pct=round(100 * float(sep.mean()), 2),
    correct_ranking_separated_pct=round(100 * float(ok[sep].mean()), 2),
    correct_ranking_within_10pct=round(100 * float(ok[~sep].mean()), 2),
)
OUT['w_bar_covering_min'] = dict(min=round(min(wcov.values()), 2), max=round(max(wcov.values()), 2),
                                 short=sorted({round(v, 1) for c, v in wcov.items() if '_short_' in c}),
                                 massdep=[round(min(v for c, v in wcov.items() if '_massdep_' in c), 1), round(max(v for c, v in wcov.items() if '_massdep_' in c), 1)],
                                 long=[round(min(v for c, v in wcov.items() if '_long_' in c), 1), round(max(v for c, v in wcov.items() if '_long_' in c), 1)])
fac = {k: 1 + 2 * DELTA / v for k, v in wcov.items()}
OUT['occupancy_factor'] = dict(short=[round(min(v for c, v in fac.items() if '_short_' in c), 3), round(max(v for c, v in fac.items() if '_short_' in c), 3)],
                               H2H3=[round(min(v for c, v in fac.items() if '_short_' not in c), 3), round(max(v for c, v in fac.items() if '_short_' not in c), 3)])
hstar = [kappa(425, 270, RS[0]) / max(fac.values()), kappa(550, 300, RS[-1]) / min(fac.values())]
OUT['coupling_budget_range_pct'] = [round(100 * x, 2) for x in hstar]
light = f[(~f.cell.str.startswith('extraheavy')) & f.family.isin(['200', '250', '270', '300', '325', '380'])]
light_all = f[f.family.isin(['200', '250', '270', '300', '325', '380'])]
OUT['light_tiers_coupled_share_pct'] = [round(100 * light_all.coop_share.min(), 1), round(100 * light_all.coop_share.max(), 1)]

# ---------------------------------------------------------------- Section 5.2: decisions priced on K_rho (shift labour)
lr = pd.read_csv(RES / 'main_load_rule.csv')
krho = {(c, fa): int(k) for c, fa, k in zip(lr.cell, lr.family, lr.K_rho)}
co = {(c, fa): x for c, fa, x in zip(f.cell, f.family, f.coop_share)}
kst = {(c, fa): int(k) for c, fa, k in zip(f.cell, f.family, f.K_final)}
same = sc_star = sc_rho = n = 0
for cell, g in f.groupby('cell'):
    fams = list(g.family)
    for mod in RC.MAIN_MODELS:
        P = RC.proxy(mod)
        for r in RS:
            cs = {fa: fleet_cost(cell, fa, kst[cell, fa], P, r) for fa in fams}
            cr = {fa: fleet_cost(cell, fa, krho[cell, fa], P, r) for fa in fams if (cell, fa) in krho}
            ws, wr = min(cs, key=cs.get), min(cr, key=cr.get)
            n += 1; same += ws == wr
            sc_star += co[cell, ws] <= 0.1 + 1e-12; sc_rho += co[cell, wr] <= 0.1 + 1e-12
OUT['K_rho_pricing'] = dict(decisions=n, single_carry_share_K_rho_pct=round(100 * sc_rho / n, 2),
                            single_carry_share_K_star_pct=round(100 * sc_star / n, 2), same_winner_pct=round(100 * same / n, 2))

# ---------------------------------------------------------------- Section 5.2: lower envelope in r (Fig. 6)
rgrid = np.exp(np.linspace(math.log(0.5), math.log(5000), 3001))
env = []
for cell, g in f.groupby('cell'):
    gi = g.set_index('family')
    for mod in RC.MAIN_MODELS:
        P = RC.proxy(mod)
        cap = {fa: P(RC.caps(cell, fa, int(v.K_final))) for fa, v in gi.iterrows()}
        for lab in RC.LAB4:
            L = {fa: RC.labour(v, lab, int(v.K_final)) for fa, v in gi.iterrows()}
            fams = list(cap)
            C = np.array([[r * cap[fa] + L[fa] for fa in fams] for r in rgrid])
            win = C.argmin(1)
            single = np.array([co[cell, fams[i]] <= 0.1 + 1e-12 for i in win])
            first = rgrid[np.argmax(~single)] if (~single).any() else None
            env.append(dict(cell=cell, model=RC.mname(mod), labour=lab, single=single, first_switch=first))
ex = [e for e in env if not e['cell'].startswith('extraheavy')]
S = np.array([e['single'] for e in ex])
share = S.mean(0)
i30 = int(np.argmin(abs(rgrid - RS[-1])))
full = rgrid[np.where(share >= 1 - 1e-12)[0].max()] if (share >= 1 - 1e-12).any() else None
sw = [e['first_switch'] for e in ex if e['first_switch'] is not None]
OUT['envelope_outside_heavy_tail'] = dict(
    combinations=len(ex), all_single_up_to_r=round(float(full), 2) if full else None,
    share_at_r30_pct=round(100 * float(share[i30]), 2), share_at_r5000_pct=round(100 * float(share[-1]), 2),
    no_switch_pct=round(100 * (1 - len(sw) / len(ex)), 2),
    switch_above_r30_pct=round(100 * float(np.mean(np.array(sw) > RS[-1])), 2) if sw else None,
    median_switch_r=round(float(np.median(sw)), 1) if sw else None,
    switches_inside_calibrated_range=[(e['cell'], e['model'], e['labour'], round(float(e['first_switch']), 2))
                                      for e in ex if e['first_switch'] is not None and e['first_switch'] <= RS[-1]])

# ---------------------------------------------------------------- Section 5.3: 300 t vs 550 t in the heavy-block share study
heavy_share = pd.read_csv(RES / 'heavy_share_fleets.csv')
heavy_share = heavy_share[heavy_share.K_final.notna()]
t7 = pd.read_csv(RES / 'runs_compact' / 'tasks_heavy_share.csv')
m7 = {c: g.mass_t.to_numpy(float) for c, g in t7.groupby('cell')}
rows7 = []
for cell, g in heavy_share.groupby('cell'):
    gi = g.set_index('family')
    if '300' not in gi.index or '550' not in gi.index:
        continue
    lo, hi = gi.loc['300'], gi.loc['550']
    npd = len(m7[cell]) / 30
    w = wbar(hi, npd)
    fac7, h = occ_factor(m7[cell], 300, w)
    for mod in RC.MAIN_MODELS:
        P = RC.proxy(mod)
        for r in RS:
            k = (r * P([550]) + ELL) / (r * P([300]) + ELL) - 1
            fluid = fac7 / (1 + k)
            sim = fleet_cost(cell, '300', lo.K_final, P, r) / fleet_cost(cell, '550', hi.K_final, P, r)
            rows7.append(dict(cell=cell, p=float(cell.split('_')[0][len('heavy'):]), handling=cell.split('_')[1], model=RC.mname(mod), r=r,
                              h=h, hstar=k / (1 + 2 * DELTA / w), fluid=fluid, sim=sim))
d7 = pd.DataFrame(rows7)
d7.to_csv(RES / 'fluid_pairs_heavy_share.csv', index=False)
ok7 = np.sign(d7.fluid - 1) == np.sign(d7.sim - 1)
OUT['heavy_share_300_vs_550'] = dict(
    comparisons=len(d7), correct_ranking_pct=round(100 * float(ok7.mean()), 2),
    pearson=round(float(np.corrcoef(d7.fluid, d7.sim)[0, 1]), 4), light_cheaper_pct=round(100 * float((d7.sim < 1).mean()), 2),
    within_budget_share_by_p={f'{p:.2f}': round(100 * float((g.h < g.hstar).mean()), 1) for p, g in d7.groupby('p')})

(RES / 'fluid_check.json').write_text(json.dumps(OUT, indent=1, default=float) + '\n', encoding='utf8')
print(json.dumps(OUT, indent=1, default=float))
