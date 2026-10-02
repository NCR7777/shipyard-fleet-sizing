"""Block-by-block decomposition of the vehicle-time of the pricing-selected schedules (no new search).

For every series of a study (default: the main study, directory `main`; optionally also the extended mixes under the
120-min cap of the delay-cap study, `T120_*` in directory `delay_cap`) the 30 schedules chosen by the pricing knapsack
(schedule_replay.chosen = analyse_study.knapsack at K*) are replayed block by block with the same forward rule as
core.evaluate (global order, earliest start, legal teams), and transporter time is split into
  empty      : empty approach, summed over team members
  sync       : waiting of early team members for the last one (core.evaluate's 'sync')
  svc_single : D_i of blocks carried alone
  svc_coup   : |S| (D_i + delta_i) of coupled blocks
  of which coup_excess = (|S| - 1) D_i + |S| delta_i (what the same block would not cost if carried alone)
  idle       : K x 16 h - work (negative = after-shift work)
plus the fluid quantities of Corollary 2: occupancy w_i = D_i + e_i (e_i = mean member approach), coupled
occupancy share h = sum_{coupled} w_i / sum_i w_i, and the mean occupancy of single-carried blocks w_single.
Totals are checked against core.evaluate (work, empty, sync, service) for every schedule.

Pairs: every family against the covering homogeneous tier of its condition (Jiang, light-skewed and uniform mass
scenarios: 500; Roh-Cha: 550; Liu: 425; extra-heavy: 550, which leaves blocks above 550 t coupled); delta work per
day and the shares of it due to coupled excess service, sync and empty travel.

  python vehicle_time.py [study=main] [workers=6] [--with-r3]
  -> results/vehicle_time_series.csv, results/vehicle_time_pairs.csv, results/vehicle_time_summary.json (other studies: vehicle_time_<study>_*)
  For the main study the per-series sync and coupled-service shares must equal `results/claim_numbers.json` (checked,
  else it stops).
  python vehicle_time.py selftest      # synthetic study, no main-yard files needed
"""
import csv
import json
import math
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
CODE = STUDY_ROOT / 'code'
sys.path.insert(0, str(CODE))
SHIFT_S = 16 * 3600
COVER = {'jiang': '500', 'lightskew': '500', 'uniform': '500', 'extraheavy': '550', 'rohcha': '550', 'liu': '425'}


def _paths():
    import schedule_replay as RP
    for sub in ('common', 'search'):
        p = str(RP.SOLVER / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    return RP


def decompose(inst, order, team):
    K = inst.K
    avail, last = [0] * K, [-1] * K
    acc = dict(empty=0.0, sync=0.0, svc_single=0.0, svc_coup=0.0, coup_excess=0.0, coup_empty=0.0,
               w_all=0.0, w_coup=0.0, w_single=0.0, n_single=0, n_coup=0)
    for i in order:
        S = team[i]
        r = inst.rel[i]
        s, arr, e_i = r, [], 0.0
        for k in S:
            t = inst.tE0[k][i] if last[k] < 0 else inst.tE[last[k]][i]
            a = avail[k] + t
            e_i += t
            arr.append(a)
            s = max(s, a)
        acc['empty'] += e_i
        acc['sync'] += sum(s - max(a, r) for a in arr)
        g = len(S)
        dd = inst.D[i] + (inst.dl[i] if g > 1 else 0)
        w = inst.D[i] + e_i / g
        acc['w_all'] += w
        if g > 1:
            acc['svc_coup'] += g * dd
            acc['coup_excess'] += (g - 1) * inst.D[i] + g * inst.dl[i]
            acc['coup_empty'] += e_i
            acc['w_coup'] += w
            acc['n_coup'] += 1
        else:
            acc['svc_single'] += dd
            acc['w_single'] += w
            acc['n_single'] += 1
        c = s + dd
        for k in S:
            avail[k], last[k] = c, i
    acc['work'] = acc['empty'] + acc['sync'] + acc['svc_single'] + acc['svc_coup']
    return acc


def one(args):
    study, sp = args
    RP = _paths()
    from core import evaluate
    K, need, ntot, keys = RP.chosen(study, sp)
    if K is None:
        return sp['name'], None
    tot = {}
    for k, s, j in keys:
        r = json.loads((study / 'runs' / sp['name'] / ('K%d_s%d_j%d.json' % (k, s, j))).read_text(encoding='utf8'))
        team = {int(i): tuple(v) for i, v in r['team'].items()}
        inst = RP.instance(study, sp, k, s)
        a = decompose(inst, r['order'], team)
        ev = evaluate(inst, r['order'], team, 0)
        for f, g in (('work', 'work'), ('empty', 'empty'), ('sync', 'sync')):
            assert abs(a[f] - ev[g]) < 1e-6 * max(1.0, ev[g]), (sp['name'], k, s, j, f, a[f], ev[g])
        assert abs(a['svc_single'] + a['svc_coup'] - ev['service']) < 1e-6 * max(1.0, ev['service'])
        a['avail'] = K * SHIFT_S                     # the fleet owns K transporters on every day (lower counts embedded)
        for f, v in a.items():
            tot[f] = tot.get(f, 0) + v
    n = len(keys)
    day = {f: v / n / 3600 for f, v in tot.items() if f not in ('n_single', 'n_coup', 'w_all', 'w_coup', 'w_single')}
    out = dict(series=sp['name'], cell=sp['cell'], family=sp['family'], K=K, days=n,
               **{f + '_h': round(v, 4) for f, v in day.items()},
               idle_h=round(day['avail'] - day['work'], 4),
               sync_share=tot['sync'] / tot['work'], coup_excess_share=tot['coup_excess'] / tot['work'],
               coop_service_share=tot['svc_coup'] / (tot['svc_single'] + tot['svc_coup']),
               h_occ=tot['w_coup'] / tot['w_all'], coup_block_share=tot['n_coup'] / (tot['n_coup'] + tot['n_single']),
               w_single_min=(tot['w_single'] / tot['n_single'] / 60) if tot['n_single'] else None,
               w_coup_min=(tot['w_coup'] / tot['n_coup'] / 60) if tot['n_coup'] else None)
    return sp['name'], out


def pairs(rows):
    by = {(r['cell'], r['family']): r for r in rows}
    out = []
    for (cell, fam), x in sorted(by.items()):
        cov = by.get((cell, COVER[cell.split('_')[0]]))
        if cov is None or fam == cov['family']:
            continue
        d = {f: x[f + '_h'] - cov[f + '_h'] for f in ('work', 'empty', 'sync', 'svc_single', 'svc_coup', 'coup_excess')}
        dw = d['work']
        out.append(dict(cell=cell, family=fam, cover=cov['family'], K=x['K'], K_cover=cov['K'], coup_block_share=x['coup_block_share'],
                        h_occ=x['h_occ'], d_work_h=round(dw, 4), d_empty_h=round(d['empty'], 4), d_sync_h=round(d['sync'], 4),
                        d_service_h=round(d['svc_single'] + d['svc_coup'], 4), coup_excess_h=round(x['coup_excess_h'], 4),
                        share_excess=(x['coup_excess_h'] / dw) if dw > 1e-9 else None,
                        share_sync=(d['sync'] / dw) if dw > 1e-9 else None,
                        rel_work=x['work_h'] / cov['work_h'] - 1))
    return out


def write(path, rows):
    keys = list(rows[0])
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def summary(rows, prs):
    q = lambda v: dict(n=len(v), median=st.median(v), p10=sorted(v)[int(0.1 * (len(v) - 1))], p90=sorted(v)[int(0.9 * (len(v) - 1))],
                       min=min(v), max=max(v)) if v else None
    cop = [p for p in prs if p['coup_block_share'] > 0.01 and not p['cell'].startswith('extraheavy') and p['d_work_h'] > 0]
    return dict(series=len(rows),
                sync_share_all=q([r['sync_share'] for r in rows]),
                coup_excess_share_all=q([r['coup_excess_share'] for r in rows]),
                w_single_min_covering=q([r['w_single_min'] for r in rows if r['family'] == COVER[r['cell'].split('_')[0]] and r['w_single_min']]),
                pairs_coupling_outside_extraheavy=len(cop),
                pair_share_of_extra_work_from_coupled_excess=q([p['share_excess'] for p in cop]),
                pair_share_of_extra_work_from_sync=q([p['share_sync'] for p in cop]),
                pair_rel_work=q([p['rel_work'] for p in cop]),
                corr_h_occ_vs_rel_work=_corr([p['h_occ'] for p in cop], [p['rel_work'] for p in cop]))


def _corr(x, y):
    if len(x) < 3:
        return None
    mx, my = st.mean(x), st.mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else None


def main(study_name='main', workers=6, with_r3=False):
    study = STUDY_ROOT / study_name
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    todo = [(study, sp) for sp in specs]
    if with_r3:
        r3 = STUDY_ROOT / 'delay_cap'
        todo += [(r3, sp) for sp in json.loads((r3 / 'series.json').read_text(encoding='utf8')) if sp['name'].startswith('T120_')]
    with ProcessPoolExecutor(workers) as ex:
        res = [r for _, r in ex.map(one, todo, chunksize=4) if r]
    prs = pairs(res)
    res_dir = STUDY_ROOT / 'results'
    tag = 'vehicle_time' if study_name == 'main' else 'vehicle_time_%s' % study_name
    s = summary(res, prs)
    c1 = res_dir / 'claim_numbers.json'
    if study_name == 'main' and c1.exists():          # check against the mechanism numbers of the main results
        ref = json.loads(c1.read_text(encoding='utf8'))['per_series']
        got = {r['series']: r for r in res}
        d = [max(abs(got[k]['sync_share'] - v['sync_share']), abs(got[k]['coop_service_share'] - v['coop_service_share']))
             for k, v in ref.items() if k in got]
        s['reproduces_claim_numbers'] = dict(series=len(d), max_abs_diff=max(d) if d else None)
        assert d and max(d) < 1e-9, ('the decomposition does not reproduce claim_numbers.json per_series; stop and report',
                                     s['reproduces_claim_numbers'])
    write(res_dir / ('%s_vt_series.csv' % tag), res)
    write(res_dir / ('%s_vt_pairs.csv' % tag), prs)
    (res_dir / ('%s_summary.json' % tag)).write_text(json.dumps(s, indent=1) + '\n', encoding='utf8')
    print(json.dumps(s, indent=1))


def selftest():
    """Synthetic study: two days of 14 blocks, a 270 t fleet that must couple the heavy blocks and a 500 t fleet that
    need not; real ALNS runs through fleet_scan.work, then the decomposition and its consistency checks."""
    import random
    import tempfile
    import fleet_scan
    RP = _paths()
    with tempfile.TemporaryDirectory() as tmp:
        study = Path(tmp) / 'T'
        (study / 'base').mkdir(parents=True)
        seeds, n, specs = [1, 2], 14, []
        base = {}
        for s in seeds:
            rng = random.Random(s)
            tasks = [dict(id='T%02d' % i, mass=rng.choice([150, 200, 250, 420]), release=1800 * (i // 4), due=1800 * (i // 4) + 14400,
                          load=600, unload=600, tauL=rng.randint(300, 900), turns=0) for i in range(n)]
            tE = [[0 if i == j else rng.randint(120, 600) for j in range(n)] for i in range(n)]
            d = dict(name='syn_s%d' % s, seed=s, tasks=tasks, vehicles=[{'id': 'V%02d' % k} for k in range(40)],
                     tauE_start=[[rng.randint(60, 400) for _ in range(n)] for _ in range(40)], tauE=tE,
                     meta=dict(delta_s=600, crew=4, max_team=3))
            p = 'base/syn_s%d.json' % s
            (study / p).write_text(json.dumps(d), encoding='utf8')
            base[str(s)] = p
        for fam in ('270', '500'):
            specs.append(dict(name='SYN_%s' % fam, cell='jiang_short_baseline', family=fam, K_start=4, K_min=3, objective='cap', tmax_s=7200,
                              seed_offset=0, gen=None, base=base, seeds=seeds, n_total=n * len(seeds)))
        (study / 'series.json').write_text(json.dumps(specs), encoding='utf8')
        for sp in specs:
            for K in (3, 4):
                for s in seeds:
                    fleet_scan.work(dict(series=sp['name'], K=K, seed=s, j=0, caps=fleet_scan.caps_of(sp['family'], K), base=base[str(s)],
                                    objective='cap', tmax_s=7200, seed_offset=0, study=str(study)))
        rows = [one((study, sp))[1] for sp in specs]
        assert all(rows), rows
        prs = pairs([dict(r, cell='jiang_short_baseline') for r in rows])
        light = rows[0]
        assert light['coup_block_share'] > 0 and light['svc_coup_h'] > 0, light
        assert rows[1]['coup_block_share'] == 0 and rows[1]['sync_h'] == 0, rows[1]
        print(json.dumps(dict(series=rows, pairs=prs), indent=1))
        print('vehicle_time self-test passed')


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if a[:1] == ['selftest']:
        selftest()
    else:
        main(a[0] if a else 'main', int(a[1]) if len(a) > 1 else 6, '--with-r3' in sys.argv)
