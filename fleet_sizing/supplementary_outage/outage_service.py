"""Service lost when one transporter is out of service (fleets of the fresh-day confirmation set at their K* in the
main results, main days 101-130).

For each fleet the outage variants in the design file `supplementary_outage/design/outage_service.json` are evaluated: a light (or, in
homogeneous fleets, any) unit out, and for mixes a heavy unit out. A variant is another fleet family at count K* - 1
(lower counts of that family embed into it), so most of its runs are already stored in the main study and the
delay-cap study (directories `main`, `delay_cap`); the missing ones are run here with that family's own series definition and
seed offset, i.e. exactly as its scan would have produced them.

Per day the best stored or new schedule is taken (most blocks on time among schedules with no block over the cap; a
day without such a schedule keeps its best uncapped schedule and is flagged). Reported per fleet: pooled on-time share
nominally and with the worst unit out on every day, days without a capped schedule, coupled-block share on outage
days, and P(specification met) when each day independently loses the worst unit with probability q (Monte Carlo).

  python outage_service.py prepare                  # -> outage/series.json, outage/jobs.json, outage/base (only the missing runs)
  pypy   outage_service.py run [workers]            # restartable
  python outage_service.py analyse [--preliminary]  # -> results/outage_service_fleets.csv, outage_service_report.json, outage_service_report.md
                                               #    (`S7bp_*`: stored runs of the main results only, fleets with
                                               #    missing runs flagged)
"""
import json
import math
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outage_service_common as C2                                      # noqa: E402

STUDY_ROOT, RES, SEEDS = C2.STUDY_ROOT, C2.RES, C2.SEEDS
STUDY = STUDY_ROOT / 'outage'
NEED = C2.need(0.95)
COVER = {'jiang': '500', 'lightskew': '500', 'uniform': '500', 'extraheavy': '550', 'rohcha': '550', 'liu': '425'}


def all_series(P):
    names = set()
    for f in P['fleets']:
        names.add(f['source']['series'])
        names |= {v['series'] for v in f['variants']}
    return sorted(names)


def missing(P, runs):
    """(variant series, K, seed, j) needed but not stored; stored runs at lower counts do not replace the runs at K."""
    need = set()
    for f in P['fleets']:
        for v in f['variants']:
            for s in SEEDS:
                for j in P['j']:
                    if (v['K'], s, j) not in runs.get(v['series'], {}):
                        need.add((v['study'], v['series'], v['family'], v['K'], s, j))
    return sorted(need)


def prepare():
    import fleet_scan
    P = C2.design('outage_service.json')
    if (STUDY / 'series.json').exists():
        sys.exit('outage already exists')
    runs = C2.compact_runs(all_series(P))
    src = {}
    for stdy in ('main', 'delay_cap'):
        for sp in json.loads((STUDY_ROOT / stdy / 'series.json').read_text(encoding='utf8')):
            src[sp['name']] = (stdy, sp)
    jobs, used = [], {}
    for stdy, name, fam, K, s, j in missing(P, runs):
        st_, sp = src[name]
        assert sp['family'] == fam and K >= sp['K_min'], (name, K)
        used[name] = sp
        C2.copy_base(STUDY_ROOT / st_, STUDY, {str(s): sp['base'][str(s)]})
        jobs.append(dict(series=name, K=K, seed=s, j=j, caps=fleet_scan.caps_of(fam, K), base=sp['base'][str(s)], objective=sp['objective'],
                         tmax_s=sp['tmax_s'], seed_offset=sp['seed_offset'], study=str(STUDY)))
    STUDY.mkdir(parents=True, exist_ok=True)
    fleet_scan.write_series(STUDY, sorted(used.values(), key=lambda sp: sp['name']))
    (STUDY / 'jobs.json').write_text(json.dumps(jobs, indent=0) + '\n', encoding='utf8')
    print(json.dumps(dict(jobs=len(jobs), series=len(used), by_series=dict(Counter(j['series'] for j in jobs)))))


def run(workers):
    import fleet_scan
    fleet_scan.freeze(STUDY)
    C2.freeze_self(STUDY, [__file__, HERE / 'outage_service_common.py'])
    jobs = json.loads((STUDY / 'jobs.json').read_text(encoding='utf8'))
    C2.run_jobs(STUDY, jobs, workers)


# ------------------------------------------------------------------ analysis
def day(runs, K, s):
    """(on, capped, coop) of the best schedule of day s among runs with count <= K; None if no run is stored."""
    opts = [v for (k, ss, j), v in runs.items() if ss == s and k <= K]
    if not opts:
        return None
    ok = [v for v in opts if v is not None]
    if not ok:
        return (0, False, 0)                              # structurally infeasible: no legal team for some block
    cap = [v for v in ok if v['over'] == 0]
    pool, capped = (cap, True) if cap else (ok, False)
    b = max(pool, key=lambda v: (v['on'], -v['crew_veh']))
    return (b['on'], capped, b['coop'])


def heavy_count(f):
    return int(f[-1]) if f.startswith('MX') else int(f.split('x')[1]) if f.startswith('L') else 0


def spearman(x, y):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            k = i
            while k + 1 < len(o) and v[o[k + 1]] == v[o[i]]:
                k += 1
            for t in range(i, k + 1):
                r[o[t]] = (i + k) / 2 + 1
            i = k + 1
        return r
    rx, ry = rank(x), rank(y)
    mx, my = st.mean(rx), st.mean(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy) if sx and sy else None


def analyse(preliminary):
    import numpy as np
    P = C2.design('outage_service.json')
    names = all_series(P)
    runs = C2.compact_runs(names)
    if not preliminary:
        for n in names:
            runs.setdefault(n, {}).update(C2.json_runs(STUDY, n))
    rng = np.random.default_rng(P['monte_carlo']['rng_seed'])
    rows = []
    for f in P['fleets']:
        nom = [day(runs[f['source']['series']], f['K_star'], s) for s in SEEDS]
        row = dict(cell=f['cell'], family=f['family'], K_star=f['K_star'], heavy_units=heavy_count(f['family']))
        assert all(x is not None and x[1] for x in nom), ('nominal fleet must qualify', f['family'], f['cell'])
        row['nominal_on'] = sum(x[0] for x in nom) / C2.NTOT
        best = None
        for v in f['variants']:
            d = [day(runs.get(v['series'], {}), v['K'], s) for s in SEEDS]
            have = sum(x is not None for x in d)
            j_full = all((v['K'], s, j) in runs.get(v['series'], {}) for s in SEEDS for j in P['j'])
            if have < len(SEEDS):
                row['%s_complete' % v['kind']] = False
                continue
            share = sum(x[0] for x in d) / C2.NTOT
            unc = sum(not x[1] for x in d)
            row.update({'%s_family' % v['kind']: v['family'], '%s_K' % v['kind']: v['K'], '%s_on' % v['kind']: share,
                        '%s_uncapped_days' % v['kind']: unc, '%s_complete' % v['kind']: j_full,
                        '%s_coop' % v['kind']: sum(x[2] for x in d) / C2.NTOT})
            if best is None or (share, -unc) < (best[1], -best[2]):
                best = (v['kind'], share, unc, d)
        complete = all(row.get('%s_complete' % v['kind'], False) for v in f['variants'])
        row['complete'] = complete
        if best is not None and len([v for v in f['variants'] if '%s_on' % v['kind'] in row]) == len(f['variants']):
            kind, share, unc, d = best
            row.update(worst=kind, outage_on=share, outage_uncapped_days=unc, loss=row['nominal_on'] - share,
                       rel_loss=(row['nominal_on'] - share) / row['nominal_on'], outage_coop=row['%s_coop' % kind],
                       meets_spec_every_day_outage=share * C2.NTOT >= NEED and unc == 0)
            n_on = np.array([x[0] for x in nom], float)
            v_on = np.array([x[0] for x in d], float)
            v_cap = np.array([x[1] for x in d], bool)
            for q in P['monte_carlo']['q']:
                out = rng.random((P['monte_carlo']['draws'], len(SEEDS))) < q
                tot = np.where(out, v_on, n_on).sum(1)
                capped = ~(out & ~v_cap).any(1)
                row['P_meet_q%.2f' % q] = float(((tot >= NEED) & capped).mean())
                row['mean_on_q%.2f' % q] = float(tot.mean() / C2.NTOT)
        rows.append(row)
    rep = dict(fleets=len(rows), complete=sum(r['complete'] for r in rows), check1=[], check2={})
    for cell in sorted({r['cell'] for r in rows}):
        g = [r for r in rows if r['cell'] == cell and 'loss' in r]
        cov = next((r for r in g if r['family'] == COVER[cell.split('_')[0]]), None)
        for r in g:
            if r['heavy_units'] == 1 and cov is not None:
                rep['check1'].append(dict(cell=cell, mix=r['family'], loss_mix=r['loss'], cover=cov['family'], loss_cover=cov['loss'],
                                      holds=r['loss'] > cov['loss'], mix_outage_coop=r['outage_coop']))
        if len(g) >= 3:
            rep['check2'][cell] = dict(n=len(g), spearman_Kstar_vs_rel_loss=spearman([r['K_star'] for r in g], [r['rel_loss'] for r in g]))
    rep['check1_holds'] = '%d / %d' % (sum(x['holds'] for x in rep['check1']), len(rep['check1']))
    rho = [v['spearman_Kstar_vs_rel_loss'] for v in rep['check2'].values() if v['spearman_Kstar_vs_rel_loss'] is not None]
    rep['check2_negative'] = '%d / %d' % (sum(x < 0 for x in rho), len(rho))
    rep['meets_spec_with_every_day_outage'] = [r['cell'] + ' ' + r['family'] for r in rows if r.get('meets_spec_every_day_outage')]
    if preliminary:
        rep['note'] = ('preliminary: stored runs of the main results only; '
                       'fleets with incomplete variants have no outage figures')
    tag = 'outage_service_preliminary' if preliminary else 'outage_service'
    C2.write_csv(RES / ('%s_fleets.csv' % tag), rows)
    (RES / ('%s_report.json' % tag)).write_text(json.dumps(rep, indent=1) + '\n', encoding='utf8')
    md = ['# One-unit outage%s' % (' (preliminary)' if preliminary else ''), '',
          '| condition | fleet | K* | nominal on-time | worst unit out | on-time, unit out every day | days uncapped | coupled share (outage) | P(meet), q = 0.05 / 0.10 / 0.20 |',
          '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        if 'loss' not in r:
            md.append('| %s | %s | %d | %.1f %% | (runs missing) | | | | |' % (r['cell'], r['family'], r['K_star'], 100 * r['nominal_on']))
            continue
        md.append('| %s | %s | %d | %.1f %% | %s | %.1f %% | %d | %.1f %% | %.2f / %.2f / %.2f |' % (
            r['cell'], r['family'], r['K_star'], 100 * r['nominal_on'], r['worst'], 100 * r['outage_on'], r['outage_uncapped_days'],
            100 * r['outage_coop'], r['P_meet_q0.05'], r['P_meet_q0.10'], r['P_meet_q0.20']))
    md += ['', 'Check 1 (one-heavy mix loses more than the covering tier): %s. '
           'Check 2 (Spearman K* vs relative loss < 0): %s.' % (
        rep['check1_holds'], rep['check2_negative'])]
    (RES / ('%s_report.md' % tag)).write_text('\n'.join(md) + '\n', encoding='utf8')
    print('\n'.join(md))
    print(json.dumps({k: v for k, v in rep.items() if k != 'check2'}, indent=1))


if __name__ == '__main__':
    a = sys.argv[1:]
    pre = '--preliminary' in a
    a = [x for x in a if not x.startswith('--')]
    {'prepare': lambda: prepare(), 'run': lambda: run(int(a[1]) if len(a) > 1 else 8),
     'analyse': lambda: analyse(pre)}[a[0]]()
