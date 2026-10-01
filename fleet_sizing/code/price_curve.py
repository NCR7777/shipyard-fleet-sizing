"""Price curve and price ratio r: price-capacity calibration. Data: the 33 A-class records of
`earlier_study/data/price_sources_R24.md` (award price and unit count verified), parsed from its
table; buyer = the 'buyer' column (end user) for clustering.

Fits (all on unit prices; VAT removed by dividing by 1.13 unless stated):
  power law ln P = a + alpha ln Q: all 33; 200-550 t (the modelled tier range), OLS / HC3 /
  cluster bootstrap by buyer (2,000 resamples, seed 20260929);
  lack-of-fit F test of the power law using the pure error of repeated capacities;
  affine P = F + vQ and a piecewise-linear curve with a break at 200 t.
r = daily capital cost of one 270-t transporter / hourly labour cost, over life 8-15 y,
interest 4-8%, 250-300 operating days, on-cost 30-40%, annual hours 2,000 (main) and
2,527 (48.6 h x 52, sensitivity), reported separately for the national production-worker and
the Shanghai manufacturing wage.
"""
import itertools
import json
import re
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'fleet_sizing' / 'results'
VAT = 1.13


def records():
    md = ROOT / 'earlier_study/data/price_sources_R24.md'
    if not md.exists():      # public release: Supplementary Table S1, whose buyer_cluster codes sort as the buyer names do
        import csv
        return [dict(id=r['id'], Q=int(r['capacity_t']), unit=float(r['award_total_CNY_incl_VAT'].replace(',', '')) / int(r['quantity']),
                     qty=int(r['quantity']), buyer=r['buyer_cluster'])
                for r in csv.DictReader(open(OUT / 'S1_price_sources.csv', encoding='utf-8-sig'))]
    t = md.read_text(encoding='utf8')
    sec = t[t.index('### 1.1 A 类'):t.index('### 1.2')]
    out = []
    for line in sec.splitlines():
        if not line.startswith('| A'):
            continue
        c = [x.strip() for x in line.strip().strip('|').split('|')]
        rid = re.match(r'A\d\d', c[0]).group(0)
        q = int(re.search(r'(\d+)', c[1]).group(1))
        total = float(c[3].replace(',', ''))
        qty = int(re.search(r'(\d+)', c[5].replace('一', '1')).group(1)) if re.search(r'\d', c[5]) else 1
        buyer = re.sub(r'（.*?）|\(.*?\)', '', c[8]).replace('招标人：', '').strip()
        out.append(dict(id=rid, Q=q, unit=total / qty, qty=qty, buyer=buyer))
    return out


def ols(x, y):
    X = np.column_stack([np.ones_like(x), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n = len(y)
    XtXi = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(e @ e / (n - 2) * XtXi))
    h = np.einsum('ij,jk,ik->i', X, XtXi, X)
    hc3 = np.sqrt(np.diag(XtXi @ (X.T * (e / (1 - h)) ** 2) @ X @ XtXi))
    t = stats.t.ppf(0.975, n - 2)
    return dict(n=n, alpha=b[1], ci=[b[1] - t * se[1], b[1] + t * se[1]], hc3=[b[1] - t * hc3[1], b[1] + t * hc3[1]], a=b[0])


def cluster_boot(rows, n=2000, seed=20260929):
    rng = np.random.default_rng(seed)
    buyers = sorted({r['buyer'] for r in rows})
    by = {b: [r for r in rows if r['buyer'] == b] for b in buyers}
    al = []
    for _ in range(n):
        pick = [r for b in rng.choice(buyers, len(buyers)) for r in by[b]]
        x = np.log([r['Q'] for r in pick])
        if np.ptp(x) == 0:
            continue
        al.append(ols(x, np.log([r['unit'] for r in pick]))['alpha'])
    return [float(np.percentile(al, 2.5)), float(np.percentile(al, 97.5))], len(buyers)


def lack_of_fit(rows):
    x = np.log([r['Q'] for r in rows])
    y = np.log([r['unit'] for r in rows])
    f = ols(x, y)
    e = y - f['a'] - f['alpha'] * x
    sse = float(e @ e)
    groups = {}
    for q, v in zip([r['Q'] for r in rows], y):
        groups.setdefault(q, []).append(v)
    sspe = sum(float(np.sum((np.array(v) - np.mean(v)) ** 2)) for v in groups.values())
    c, n = len(groups), len(rows)
    F = ((sse - sspe) / (c - 2)) / (sspe / (n - c))
    return dict(F=F, df=(c - 2, n - c), p=float(1 - stats.f.cdf(F, c - 2, n - c)), levels=c)


def price_curves(rows):
    Q = np.array([r['Q'] for r in rows], float)
    P = np.array([r['unit'] for r in rows]) / VAT
    v, F = np.polyfit(Q, P, 1)
    # piecewise linear with a break at 200 t (continuous): P = b0 + b1 Q + b2 max(0, Q - 200)
    X = np.column_stack([np.ones_like(Q), Q, np.maximum(0, Q - 200)])
    b, *_ = np.linalg.lstsq(X, P, rcond=None)
    return dict(affine=dict(F=F, v=v), piecewise=dict(b0=b[0], b1=b[1], b2=b[2], brk=200))


def price(model, q, curves):
    if model == 'affine':
        return curves['affine']['F'] + curves['affine']['v'] * q
    c = curves['piecewise']
    return c['b0'] + c['b1'] * q + c['b2'] * max(0, q - c['brk'])


def r_range(p270, wage, hours):
    rs = []
    for oc, n, i, days in itertools.product((0.30, 0.40), (8, 10, 15), (0.04, 0.06, 0.08), (250, 300)):
        crf = i / (1 - (1 + i) ** -n)
        rs.append(p270 * crf / days / (wage * (1 + oc) / hours))
    return [min(rs), max(rs)]


def main():
    rows = records()
    assert len(rows) == 33 and sum(r['qty'] for r in rows) == 39, (len(rows), sum(r['qty'] for r in rows))
    x = np.log([r['Q'] for r in rows])
    out = dict(records=33, units=39, buyers=len({r['buyer'] for r in rows}))
    out['all_incl_vat'] = ols(x, np.log([r['unit'] for r in rows]))
    sub = [r for r in rows if 200 <= r['Q'] <= 550]
    f = ols(np.log([r['Q'] for r in sub]), np.log([r['unit'] for r in sub]))
    f['cluster_boot'], f['clusters'] = cluster_boot(sub)
    out['range_200_550'] = f
    out['all_cluster_boot'] = cluster_boot(rows)[0]
    out['lack_of_fit_all'] = lack_of_fit(rows)
    cur = price_curves(rows)
    out['curves_ex_vat'] = cur
    p270 = {m: price(m, 270, cur) for m in ('affine', 'piecewise')}
    out['p270_ex_vat'] = p270
    wages = {'national': 79182, 'shanghai': 184833}
    out['r'] = {'%s_%dh' % (w, h): [round(v, 1) for v in r_range(p270['affine'], wages[w], h)]
                for w in wages for h in (2000, 2527)}
    out['r_union_main'] = [min(out['r']['national_2000h'][0], out['r']['shanghai_2000h'][0]),
                           max(out['r']['national_2000h'][1], out['r']['shanghai_2000h'][1])]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'price_curve.json').write_text(json.dumps(out, indent=1, default=float) + '\n', encoding='utf8')
    print(json.dumps(out, indent=1, default=lambda v: round(float(v), 3)))


if __name__ == '__main__':
    main()
