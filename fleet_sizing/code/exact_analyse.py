"""Analysis of the exact comparison on single-batch instances (directory `exact`).

Exact arm (`exact/exact/*.jsonl`). Per instance and K: proven late bound lb (INFEASIBLE = no capped schedule) and
found late ub (replay-checked). Proposition 1 (a fleet at K is the fleet at K + 1 minus its last transporter)
transfers bounds downwards (lb_eff(K) = max over K' >= K) and schedules upwards (ub_eff(K) = min over K' <= K).
K fails if some instance has no capped schedule or sum lb_eff > allowance; passes if every instance has a
schedule and sum ub_eff <= allowance. K_ub = smallest passing K; K_lb = largest failing K + 1 (floor if none).
Other arms: ALNS pipeline (K_final) and levels single / cp0 / cp100 / cp300 from analyse_study on this study;
greedy from results/exact_greedy.json.
Pricing: cost_decisions (MAIN_MODELS x main_r(), SUB for MX heavy members), labour shift_h = 64 K only.
Certified: winner W (priced at K_ub) costs no more than every other family priced at its K_lb.
Agreement: an arm's cheapest family (at its own counts) is among the certified winners (exact ties count).
Near-tie (search dependence): some losing family X with K_ub_X - 1 >= floor would undercut the winner at K_ub_X - 1.
Regret (disagreements): chosen family at its exact counts [K_lb, K_ub] vs the winner, per cent.
Consistency checks (must all be 0): ALNS below a proven bound; an arm's K* below the exact K_lb; exact
monotonicity (a proven bound at K + 1 above a found schedule at K); replay failures.

  python exact_analyse.py            # results/exact_kstar.csv, exact_decisions.csv, exact_gap.csv, exact_summary.md
  python exact_analyse.py selfcheck
"""
import csv
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
EXACT_DIR = STUDY_ROOT / 'exact'
RES = STUDY_ROOT / 'results'
sys.path.insert(0, str(HERE))
INF = math.inf
ARMS = ('final', 'single', 'cp0', 'cp100', 'cp300', 'greedy')


def allowance(sp):
    return sp['n_total'] - math.ceil(0.95 * sp['n_total'] - 1e-9)


def load_exact(sp, d=EXACT_DIR / 'exact'):
    recs = {}
    p = d / ('%s.jsonl' % sp['name'])
    if p.exists():
        for r in map(json.loads, p.read_text(encoding='utf8').splitlines()):
            recs[r['K'], r['seed']] = r
    return recs


def raw_bounds(r):
    """(lb, ub) of one record; lb = INF when no capped schedule exists."""
    if r['status'] == 'INFEASIBLE':
        return INF, None
    ub = r['late'] if r.get('late') is not None and r.get('replay', {}).get('ok') else None
    return (r.get('late_lb') or 0), ub


def interval(sp, recs):
    seeds, allowed = sp['seeds'], allowance(sp)
    Ks = list(range(sp['K_min'], sp['hi_limit'] + 1))
    raw = {(K, s): raw_bounds(recs[K, s]) for (K, s) in recs}
    lb = {(K, s): max([raw[k, s][0] for k in Ks if k >= K and (k, s) in raw] or [0]) for K in Ks for s in seeds}
    ub = {}
    for s in seeds:
        best = None
        for K in Ks:
            u = raw.get((K, s), (0, None))[1]
            if u is not None and (best is None or u < best):
                best = u
            ub[K, s] = best
    verdict = {}
    for K in Ks:
        if any(lb[K, s] == INF for s in seeds) or sum(lb[K, s] for s in seeds) > allowed:
            verdict[K] = 'fail'
        elif all(ub[K, s] is not None for s in seeds) and sum(ub[K, s] for s in seeds) <= allowed:
            verdict[K] = 'pass'
        else:
            verdict[K] = 'open'
    k_ub = next((K for K in Ks if verdict[K] == 'pass'), None)
    fails = [K for K in Ks if verdict[K] == 'fail' and (k_ub is None or K < k_ub)]
    k_lb = max(fails) + 1 if fails else sp['K_min']
    return dict(K_lb=k_lb, K_ub=k_ub, exact=k_ub is not None and k_lb == k_ub, verdict=verdict, lb=lb, ub=ub)


def consistency(sp, recs, iv, alns_runs, arm_k):
    out = dict(alns_below_bound=0, arm_below_klb=0, monotonicity=0, replay=0)
    for (K, s), r in recs.items():
        if r.get('replay') and not r['replay']['ok']:
            out['replay'] += 1
        lo, _ = raw_bounds(r)
        _, u_prev = raw_bounds(recs[K - 1, s]) if (K - 1, s) in recs else (0, None)
        if u_prev is not None and lo > u_prev:
            out['monotonicity'] += 1
    n = {s: (recs[next(k for k in recs if k[1] == s)]['n'] if any(k[1] == s for k in recs) else None) for s in sp['seeds']}
    for (K, s, j), v in alns_runs.items():
        if v is None or (K, s) not in iv['lb'] or n[s] is None:
            continue
        if v['over'] == 0 and n[s] - v['on'] < iv['lb'][K, s]:
            out['alns_below_bound'] += 1
    for arm, k in arm_k.items():
        if k is not None and k < iv['K_lb']:
            out['arm_below_klb'] += 1
    return out


def gap_rows(sp, recs, alns_runs):
    rows = []
    for (K, s), r in recs.items():
        if not r.get('proven') or r['late'] is None:
            continue
        runs = {j: alns_runs.get((K, s, j)) for j in (0, 1, 2) if (K, s, j) in alns_runs}
        if 0 not in runs or runs[0] is None:
            continue
        late = {j: (r['n'] - v['on'] if v['over'] == 0 else None) for j, v in runs.items() if v is not None}
        best = [x for x in late.values() if x is not None]
        rows.append(dict(series=sp['name'], K=K, seed=s, opt=r['late'], alns_j0=late.get(0), alns_best=min(best) if best else None,
                         n_runs=len(late)))
    return rows


def price(cell, fam, K, P, r):
    import cost_decisions as C
    return r * P(C.caps(cell, fam, K)) + 64 * K


def decide(cell, specs, ivs, arms, models, rs):
    """specs/ivs: family -> spec / exact interval; arms: arm -> family -> K (None = no count)."""
    import cost_decisions as C
    rows = []
    for m in models:
        P = C.proxy(m)
        for r in rs:
            cost = lambda f, K: price(cell, f, K, P, r)
            lo = {f: cost(f, iv['K_lb']) for f, iv in ivs.items()}
            hi = {f: cost(f, iv['K_ub']) for f, iv in ivs.items() if iv['K_ub'] is not None}
            winners = sorted(f for f in hi if all(hi[f] <= lo[x] for x in ivs if x != f))
            row = dict(cell=cell, model=C.mname(m), r=r, certified=bool(winners), exact_winners=' '.join(winners),
                       near_tie=None, near_by='')
            if winners:
                w = winners[0]
                near = [x for x in ivs if x not in winners and ivs[x]['K_ub'] is not None and ivs[x]['K_ub'] - 1 >= specs[x]['K_min']
                        and cost(x, ivs[x]['K_ub'] - 1) < hi[w]]
                row.update(near_tie=bool(near), near_by=' '.join(sorted(near)))
            for arm, ks in arms.items():
                c = {f: cost(f, k) for f, k in ks.items() if k is not None}
                if not c:
                    row[arm] = ''
                    continue
                best = min(c.values())
                pick = sorted(f for f, v in c.items() if v == best)
                row[arm] = ' '.join(pick)
                if winners:
                    row[arm + '_agree'] = bool(set(pick) & set(winners))
                    if not row[arm + '_agree']:
                        f = pick[0]
                        row[arm + '_regret_lo'] = lo[f] / hi[winners[0]] - 1
                        row[arm + '_regret_hi'] = hi[f] / hi[winners[0]] - 1 if f in hi else None
            rows.append(row)
    return rows


def tier(rows):
    cert = [r for r in rows if r['certified']]
    agree = [r for r in cert if r['final_agree']]
    dis = [r for r in cert if not r['final_agree']]
    rate = len(agree) / len(cert) if cert else None
    if cert and not dis:
        t = 'A'
    elif cert and rate >= 0.95 and all(r['near_tie'] for r in dis):
        t = 'B'
    else:
        t = 'C'
    return t, dict(certified=len(cert), uncertified=len(rows) - len(cert), agree=len(agree), rate=rate,
                   near_tie_disagreements=sum(r['near_tie'] for r in dis),
                   separated=sum(not r['near_tie'] for r in cert), agree_separated=sum(r['final_agree'] and not r['near_tie'] for r in cert),
                   near=sum(r['near_tie'] for r in cert), agree_near=sum(r['final_agree'] and r['near_tie'] for r in cert),
                   **{arm: (sum(r.get(arm + '_agree', False) for r in cert) / len(cert) if cert else None) for arm in ARMS})


def main():
    import analyse_study as A
    import cost_decisions as C
    specs = json.loads((EXACT_DIR / 'series.json').read_text(encoding='utf8'))
    alns = {r['series']: r for r in A.analyse(EXACT_DIR)}
    gp = RES / 'exact_greedy.json'
    greedy = json.loads(gp.read_text(encoding='utf8')) if gp.exists() else {}
    kst, gaps, checks, by_cell = [], [], dict(alns_below_bound=0, arm_below_klb=0, monotonicity=0, replay=0), {}
    for sp in specs:
        recs = load_exact(sp)
        iv = interval(sp, recs)
        a = alns.get(sp['name'], {})
        ks = {arm: a.get('K_' + arm) for arm in ARMS if arm != 'greedy'}
        ks['greedy'] = greedy.get(sp['name'], {}).get('K_greedy')
        runs = A.load(EXACT_DIR, sp)
        for k, v in consistency(sp, recs, iv, runs, ks).items():
            checks[k] += v
        gaps += gap_rows(sp, recs, runs)
        diff = {arm: (None if k is None or not iv['exact'] else k - iv['K_ub']) for arm, k in ks.items()}
        kst.append(dict(series=sp['name'], cell=sp['cell'], family=sp['family'], floor=sp['K_min'], ceiling=sp['hi_limit'],
                        K_lb=iv['K_lb'], K_ub=iv['K_ub'], exact=iv['exact'], **{'K_' + arm: k for arm, k in ks.items()},
                        **{'d_' + arm: v for arm, v in diff.items()}, boundary_checked=a.get('boundary_checked')))
        by_cell.setdefault(sp['cell'], {})[sp['family']] = (sp, iv, ks)
    rows = []
    for cell, fams in sorted(by_cell.items()):
        rows += decide(cell, {f: v[0] for f, v in fams.items()}, {f: v[1] for f, v in fams.items()},
                       {arm: {f: v[2][arm] for f, v in fams.items()} for arm in ARMS}, C.MAIN_MODELS, C.main_r())
    write(RES / 'exact_kstar.csv', kst)
    write(RES / 'exact_decisions.csv', rows)
    write(RES / 'exact_gap.csv', gaps)
    t, s = tier(rows)
    summary(t, s, kst, gaps, checks, rows)


def write(path, rows):
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def summary(t, s, kst, gaps, checks, rows):
    ex = [r for r in kst if r['exact']]
    L = ['# Exact comparison on single-batch instances: summary', '', '## Consistency checks (must all be 0)', '', json.dumps(checks), '',
         '## Exact counts', '', '%d of %d series have a proven K*; %d have an interval; %d have no passing count up to the ceiling.'
         % (len(ex), len(kst), sum(r['K_ub'] is not None and not r['exact'] for r in kst), sum(r['K_ub'] is None for r in kst)), '']
    for arm in ARMS:
        d = [r['d_' + arm] for r in ex if r['d_' + arm] is not None]
        L.append('- %s: same %d, +1 %d, +2 or more %d, below %d, no count %d' % (
            arm, sum(x == 0 for x in d), sum(x == 1 for x in d), sum(x >= 2 for x in d), sum(x < 0 for x in d),
            sum(r['K_' + arm] is None for r in ex)))
    L += ['', '## Primary endpoint', '', 'Tier %s. %s' % (t, json.dumps(s)), '']
    for key, lab in (('alns_j0', 'single run (j = 0)'), ('alns_best', 'best of the available runs')):
        g = [r for r in gaps if r[key] is not None or r['alns_j0'] is None]
        ok = [r for r in gaps if r[key] is not None]
        ex_ = [r[key] - r['opt'] for r in ok]
        L.append('- ALNS %s on %d proven (instance, K): optimal %d; excess mean %.3f, max %s; over the cap %d' % (
            lab, len(gaps), sum(x == 0 for x in ex_), statistics.mean(ex_) if ex_ else float('nan'), max(ex_) if ex_ else None,
            sum(r[key] is None for r in gaps)))
    dis = [r for r in rows if r['certified'] and not r['final_agree']]
    if dis:
        reg = [r['final_regret_lo'] for r in dis]
        L.append('- Regret of the pipeline where it disagrees (lower end): median %.1f%%, max %.1f%%' % (
            100 * statistics.median(reg), 100 * max(reg)))
    (RES / 'exact_summary.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(L))


def selfcheck():
    sp = dict(name='x', seeds=[1, 2], n_total=40, K_min=2, hi_limit=6)          # allowance 2
    rec = lambda K, s, st, late, lb: dict(K=K, seed=s, status=st, late=late, late_lb=lb, n=20, replay=dict(ok=True))
    recs = {(2, 1): rec(2, 1, 'INFEASIBLE', None, None), (2, 2): rec(2, 2, 'OPTIMAL', 5, 5),
            (3, 1): rec(3, 1, 'FEASIBLE', 3, 1), (3, 2): rec(3, 2, 'FEASIBLE', 2, 1),
            (4, 1): rec(4, 1, 'OPTIMAL', 1, 1), (4, 2): rec(4, 2, 'FEASIBLE', 2, 0),
            (5, 1): rec(5, 1, 'OPTIMAL', 0, 0), (5, 2): rec(5, 2, 'OPTIMAL', 1, 1)}
    iv = interval(sp, recs)
    # K=3: lb 1+1 = 2 not > 2 -> open; K=4: ub 1+2 = 3 > 2, lb 1+1 -> open; K=5: ub 0+1 -> pass; K=2 fail
    assert (iv['K_lb'], iv['K_ub'], iv['exact']) == (3, 5, False), iv
    recs[3, 2] = rec(3, 2, 'OPTIMAL', 2, 2)                                        # lb 1+2 = 3 > 2 -> K=3 fails
    recs[4, 2] = rec(4, 2, 'OPTIMAL', 2, 2)                                        # K=4: lb 1+2 -> fails
    iv = interval(sp, recs)
    assert (iv['K_lb'], iv['K_ub'], iv['exact']) == (5, 5, True), iv
    # transfer: a bound proven at K=5 lifts K=4; a schedule found at K=3 serves K=4
    recs2 = {(3, 1): rec(3, 1, 'FEASIBLE', 0, 0), (3, 2): rec(3, 2, 'FEASIBLE', 1, 0), (4, 1): rec(4, 1, 'FEASIBLE', 5, 0),
             (4, 2): rec(4, 2, 'FEASIBLE', 5, 0)}
    assert interval(dict(sp, K_min=3), recs2)['verdict'][4] == 'pass'
    c = consistency(sp, recs, iv, {(5, 1, 0): dict(on=20, over=0), (5, 2, 0): dict(on=20, over=0)}, dict(final=4, greedy=6))
    assert c == dict(alns_below_bound=1, arm_below_klb=1, monotonicity=0, replay=0), c
    # certification and agreement with a synthetic cell
    ivs = {'550': dict(K_lb=2, K_ub=2), '300': dict(K_lb=3, K_ub=4), 'MX1': dict(K_lb=3, K_ub=3)}
    specs = {f: dict(K_min=1) for f in ivs}
    rows = decide('rohcha_short_baseline', specs, ivs, dict(final={'550': 2, '300': 4, 'MX1': 3}, greedy={'550': 3, '300': 5, 'MX1': 4}),
                  (('power', 1.0),), (1.0, 100.0))
    # r = 1: 550 x 2 (132.07) certified, MX1 at K - 1 = 2 (131.04) undercuts it -> near-tie;
    # r = 100: 300 t at its K_lb = 3 (525.3) could undercut 550 x 2 (535.4) -> not certified
    assert rows[0]['certified'] and rows[0]['final_agree'] and rows[0]['near_tie'] and rows[0]['near_by'] == 'MX1', rows[0]
    assert not rows[1]['certified'] and 'final_agree' not in rows[1], rows[1]
    print('exact_analyse self-check passed:', [(r['r'], r['exact_winners'], r['greedy'], r.get('greedy_agree'), r['near_tie']) for r in rows])


if __name__ == '__main__':
    if sys.argv[1:2] == ['selfcheck']:
        selfcheck()
    else:
        main()
