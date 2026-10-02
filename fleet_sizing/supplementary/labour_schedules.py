"""Supplementary experiment: schedule re-selection for each labour measure (no new runs).

For every fleet series of the main study and every labour measure, choose one stored run per day
(count <= K, no block over the cap) so that the 30-day on-time total meets the target and the chosen
labour measure is minimal; do this for every fully tested count K >= K*, price each (series, K) and take
the cheapest count. Decisions are then recomputed on the main grid (5 price curves x 9 r x 4 labour).

Inputs : `fleet_sizing/results/runs_compact/main.csv`, `main_fleets.csv`, `price_curve.json` (via cost_decisions)
Outputs: results/labour_schedules_series.csv (per series x labour: best K, labour, coupled share), results/labour_schedules_decisions.csv,
         results/labour_schedules_summary.json
  python labour_schedules.py            # from fleet_sizing/supplementary; about one minute
"""
import csv, json, math, sys
from pathlib import Path
import pandas as pd

STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT / 'code'))
import cost_decisions as RC                                   # noqa: E402

RES = STUDY_ROOT / 'results'
NDAY, NBLK = 30, 97
SLACK = NDAY * NBLK - math.ceil(0.95 * NDAY * NBLK - 1e-9)   # 145 late blocks allowed
LABS = {'shift_h': None, 'shift_ot_h': 'after_h', 'crew_veh_h': 'crew_veh_h', 'crew_team_h': 'crew_team_h'}


def select(day_opts, key):
    """day_opts: list (per day) of DataFrames of eligible runs. Min sum(key) s.t. sum(97 - on) <= SLACK.
    Returns (sum_key, sum_on, sum_coop) or None."""
    INF = float('inf')
    dp = {0: (0.0, 0, 0)}                                   # deficit -> (cost, on, coop)
    for o in day_opts:
        if o.empty:
            return None
        opts = list(zip(NBLK - o.on_time, o[key] if key else 0 * o.on_time, o.on_time, o.n_coop))
        # Pareto filter on (deficit, cost)
        opts.sort(key=lambda x: (x[0], x[1]))
        par, best = [], INF
        for x in opts:
            if x[1] < best - 1e-12:
                par.append(x); best = x[1]
        nd = {}
        for d, (c, on, cp) in dp.items():
            for de, ck, onx, cpx in par:
                d2 = d + de
                if d2 > SLACK:
                    continue
                v = (c + ck, on + onx, cp + cpx)
                if d2 not in nd or v[0] < nd[d2][0] - 1e-12:
                    nd[d2] = v
        dp = nd
        if not dp:
            return None
    return min(dp.values(), key=lambda v: v[0])


def main():
    runs = pd.read_csv(RES / 'runs_compact' / 'main.csv')
    runs = runs[(runs.status == 'OK') & (runs.n_over == 0)]
    fl = pd.read_csv(RES / 'main_fleets.csv').set_index('series')
    rows = []
    for s, g in runs.groupby('series'):
        kstar = int(fl.loc[s, 'K_final'])
        tested = sorted(g.K.unique())
        for K in [k for k in tested if k >= kstar]:
            sub = g[g.K <= K]
            day_opts = [sub[sub.seed == d] for d in range(101, 131)]
            for lab, key in LABS.items():
                if lab == 'shift_h':
                    res = select(day_opts, 'crew_veh_h')          # schedule irrelevant to cost; report crew-veh selection
                    lab_val = 64 * K if res else None
                else:
                    res = select(day_opts, key)
                    if res is None:
                        lab_val = None
                    elif lab == 'shift_ot_h':
                        lab_val = 64 * K + 1.5 * 4 * res[0] / NDAY
                    else:
                        lab_val = res[0] / NDAY
                if res is None:
                    continue
                rows.append(dict(series=s, cell=fl.loc[s, 'cell'], family=fl.loc[s, 'family'], K=K, K_star=kstar,
                                 labour=lab, L=lab_val, coop_share=res[2] / (NDAY * NBLK), on_time=res[1]))
    ser = pd.DataFrame(rows)
    ser.to_csv(RES / 'labour_schedules_series.csv', index=False)
    # decisions: for each setting, each family's cost = min over its K of r*P(K) + L(K, lab)
    rs, out = RC.main_r(), []
    for cell, gc in ser.groupby('cell'):
        for m in RC.MAIN_MODELS:
            P = RC.proxy(m)
            for r in rs:
                for lab in LABS:
                    gl = gc[gc.labour == lab]
                    best = {}
                    for fam, gf in gl.groupby('family'):
                        c = [(r * P(RC.caps(cell, fam, int(x.K))) + x.L, int(x.K), x.coop_share) for x in gf.itertuples()]
                        best[fam] = min(c)
                    w = min(best, key=lambda f: best[f][0])
                    srt = sorted(v[0] for v in best.values())
                    out.append(dict(cell=cell, model=RC.mname(m), r=r, labour=lab, winner=w, K=best[w][1],
                                    coop=best[w][2], margin=srt[1] / srt[0] - 1))
    dec = pd.DataFrame(out)
    dec.to_csv(RES / 'labour_schedules_decisions.csv', index=False)
    ref = pd.read_csv(RES / 'main_decisions.csv')
    m = dec.merge(ref[['cell', 'model', 'labour', 'r', 'winner']], on=['cell', 'model', 'labour'], suffixes=('', '_ref'))
    m = m[(m.r - m.r_ref).abs() < 1e-9]
    ex = ~dec.cell.str.startswith('extraheavy')
    summ = dict(settings=len(dec),
                single_carry_share=float((dec.coop <= 0.10 + 1e-12).mean()),
                single_carry_share_outside_extraheavy=float((dec[ex].coop <= 0.10 + 1e-12).mean()),
                by_labour={l: float((g.coop <= 0.10 + 1e-12).mean()) for l, g in dec.groupby('labour')},
                same_winner_as_reported=float((m.winner == m.winner_ref).mean()),
                same_winner_by_labour={l: float((g.winner == g.winner_ref).mean()) for l, g in m.groupby('labour')},
                winner_at_count_above_Kstar=float((dec.merge(ser[['series', 'K_star']].drop_duplicates(), how='left',
                                                   left_on=dec.cell + '_' + dec.winner, right_on='series').eval('K > K_star')).mean()))
    (RES / 'labour_schedules_summary.json').write_text(json.dumps(summ, indent=1) + '\n')
    print(json.dumps(summ, indent=1))


if __name__ == '__main__':
    main()
