"""Supplementary tables of the transporter price sources (S1) and of the capital-to-labour price ratio r
(`S2_price_ratio.csv`).

S1: the 33 award records of earlier_study/data/price_sources_R24.md, section 1.1 (the same rows and parser as
price_curve.records), in English: descriptive fields translated, buyers by English name, the notice excerpt kept in the
original Chinese, dates and announcement links as published. buyer_cluster numbers the buyers in the order of the
cluster bootstrap, so that price_curve refits identically from S1 alone in the public release (no working record).
Price-ratio table: every combination behind the calibrated interval of r (price_curve.r_range): capital recovery over
8, 10 or 15 years at 4, 6 or 8% interest, 250 or 300 operating days, 30 or 40% employer on-costs, two wage anchors
and two annual-hour bases, with the affine price of a 270 t transporter (VAT removed) from results/price_curve.json.
The interval limits must equal price_curve.json.

  python make_supplementary.py   -> results/S1_price_sources.csv, results/S2_price_ratio.csv
"""
import csv
import itertools
import json
import re
from pathlib import Path

import price_curve as R

HERE = Path(__file__).resolve().parent
RES = HERE.parent / 'results'
WAGES = {'national': (79182, 'National Bureau of Statistics of China, 2025 average wage of enterprises above designated size, '
                              'manufacturing, production and related workers (table 7)'),
         'shanghai': (184833, 'China Statistical Yearbook 2025, table 4-12, urban non-private units, manufacturing, Shanghai (2024)')}


# Supplementary Table S1 in English. Free-text fields are matched by a distinctive substring of
# the working record; every value must match exactly one entry, and no Chinese may remain outside the excerpt column.
DESC = [('"分段运输车"', '"block transporter"; drive not stated'),
        ('"动力平板运输车"', '"powered platform transporter"'),
        ('"平板车"', '"platform trailer"; drive not stated'),
        ('7 轴线', '"platform transporter", 7 axle lines, deck 6 x 20 m; drive not stated'),
        ('液压升降平板车', '"hydraulic lifting platform trailer"; drive not stated'),
        ('液压运输平板车', '"hydraulic transport platform trailer", axle lines/suspensions 8/16; drive not stated'),
        ('"自升式液压平板车"', '"self-lifting hydraulic platform trailer"; drive not stated'),
        ('"重型平板运输车"，驱动', '"heavy-duty platform transporter"; drive not stated'),
        ('空载平地速度', '"heavy-duty platform transporter"; "unladen speed on level ground 0-10 km/h" (travel speed stated; '
                   'presumed self-propelled)'),
        ('重型平板运输车设备', '"heavy-duty platform transporter equipment"; drive not stated'),
        ('重型自升式', '"heavy-duty self-lifting hydraulic platform transporter"; drive not stated'),
        ('驱动轮架数量', '"number of driven bogies >= 4" (driven; "self-propelled" not stated)'),
        ('**自行式**液压平板车', 'self-propelled hydraulic platform trailer'),
        ('**自行式**液压平板运输车', 'self-propelled hydraulic platform transporter'),
        ('大型液压平板车', 'large hydraulic platform trailer, axle lines/bogies 8/16; drive not stated'),
        ('大型液压平板运输车', 'large hydraulic platform transporter'),
        ('轴线/轮架 5/10', 'hydraulic platform trailer, axle lines/bogies 5/10; drive not stated'),
        ('液压平板车，驱动未写', 'hydraulic platform trailer; drive not stated'),
        ('发动机架', 'hydraulic platform transporter; "engine frame"'),
        ('自行式平板运输车', 'self-propelled platform transporter'),
        ('自行式液压平板车', 'self-propelled hydraulic platform trailer')]
AMOUNT = {'中标价格': 'award price', '中标总价': 'award total', '中标金额': 'award amount', '成交价格': 'transaction price'}
DATE = {'2022-09-29（2022-10-17 重发）': '2022-09-29 (reissued 2022-10-17)',
        '2022-09-29（2022-10-19 重发）': '2022-09-29 (reissued 2022-10-19)',
        '2025-08-27（平台日期）': '2025-08-27 (platform date)',
        '2026-03-04（平台日期 2026-03-10）': '2026-03-04 (platform date 2026-03-10)',
        '2026-03-16（平台日期；PDF 无落款日期）': '2026-03-16 (platform date; the PDF is undated)',
        '2026-06-16（平台日期）': '2026-06-16 (platform date)', '2026-06-23（平台日期）': '2026-06-23 (platform date)'}
# Official English names where the company, its group, its annual report, a licensor or its own exhibitor entry gives
# one (checked 2026-10-01); Hanyu Pinyin where none was found.
BUYER = {'上海东鼎钢结构有限公司': 'Shanghai Dongding Steel Structure Co., Ltd.',
         '上海外高桥造船有限公司': 'Shanghai Waigaoqiao Shipbuilding Co., Ltd.',
         '上海外高桥造船海洋工程有限公司': 'Shanghai Waigaoqiao Shipbuilding and Offshore Co., Ltd.',
         '中国船舶集团国际工程有限公司': 'CSSC International Engineering Co., Ltd.',
         '中国船舶集团青岛北海造船有限公司': 'CSSC Qingdao Beihai Shipbuilding Co., Ltd.',
         '中船发动机有限公司': 'CSSC Engine Co., Ltd.',
         '中船海洋动力部件有限公司': 'Zhongchuan Haiyang Dongli Bujian Youxian Gongsi',
         '中船港航船舶有限公司': 'Zhongchuan Ganghang (Guangdong) Chuanbo Youxian Gongsi',
         '中船澄西扬州船舶有限公司': 'Zhongchuan Chengxi Yangzhou Chuanbo Youxian Gongsi',
         '中船澄西船舶修造有限公司': 'Chengxi Shipyard Co., Ltd.',
         '中船澄西装备科技有限公司': 'CSSC Chengxi (Taizhou) Equipment Technology Co., Ltd.',
         '中船第九设计研究院工程有限公司': 'China Shipbuilding NDRI Engineering Co., Ltd.',
         '中船黄埔文冲船舶有限公司': 'CSSC Huangpu Wenchong Shipbuilding Company Limited',
         '大连船用柴油机有限公司': 'Dalian Marine Diesel Co., Ltd.',
         '山海关船舶重工有限责任公司': 'Shanhaiguan Shipbuilding Industry Co., Ltd.',
         '广船国际有限公司': 'Guangzhou Shipyard International Company Limited',
         '武昌船舶重工集团有限公司': 'Wuchang Shipbuilding Industry Group Co., Ltd.',
         '武汉武船重型装备工程有限责任公司': 'Wuhan Wuchuan Heavy Equipment Engineering Co., Ltd.',
         '江南造船有限责任公司': 'Jiangnan Shipyard (Group) Co., Ltd.',
         '沪东中华造船有限公司': 'Hudong-Zhonghua Shipbuilding (Group) Co., Ltd.',
         '沪东重机有限公司': 'Hudong Heavy Machinery Co., Ltd.',
         '青岛海西重机有限责任公司': 'Qingdao Haixi Heavy-duty Machinery Co., Ltd.'}
BUYER_NOTE = [('（非船厂）', 'not a shipyard'), ('柴油机厂，非船厂', 'diesel-engine works, not a shipyard'),
              ('装备厂，非船厂', 'equipment plant, not a shipyard'), ('起重机厂，非船厂', 'crane works, not a shipyard'),
              ('平台列表标题', 'listed on the platform under Guangzhou Shipyard International; the tenderer in the PDF is this company'),
              ('交货地：青岛北海', 'delivery to the Qingdao Beihai Shipbuilding yard'),
              ('招标人：', 'tenderer, for the green ship-repair upgrade project of Qingdao Beihai Shipbuilding')]
NOTES = [('P2 的台数', 'Quantity and award price verified from this notice.'),
         ('P3 的中标价', 'Award price verified from this notice; whether the type is self-propelled is not stated.'),
         ('P5 的台数', 'Quantity is 2 units; the candidate bids of CNY 7.24 / 7.16 / 8.10 million are all totals for 2 units.'),
         ('两家候选人报价均为', 'Both candidates bid CNY 2,450,000.'),
         ('扬州市江都区', 'Delivery: user site, Jiangdu District, Yangzhou. Candidates: CNY 3.625 / 3.76 million.'),
         ('高 54%', 'Candidates: CNY 1,510,000 (Wanshan) / 980,000 (Henan Haitai) / 1,350,000 (Jiangsu Haipeng); '
                   'the award price is 54% above the lowest bid.'),
         ('1,650,000 / 1,700,000', 'Candidates: CNY 1,650,000 / 1,700,000 / 1,755,000.'),
         ('1,950,000 / 1,935,000', 'Candidates: CNY 1,950,000 / 1,935,000.'),
         ('1,955,000 / 1,840,000', 'Candidates: CNY 1,955,000 / 1,840,000 (Jiangsu Haipeng).'),
         ('187.5 / 219.8', 'Candidates: CNY 1.875 / 2.198 / 2.33 million.'),
         ('2,130,000 / 2,155,000', 'Candidates: CNY 2,130,000 / 2,155,000 (Xin Dafang) / 2,228,000.'),
         ('2,400,000 / 2,190,000', 'Candidates: CNY 2,400,000 / 2,190,000 (Tianye Tonglian) / 2,396,000 (Henan Haitai).'),
         ('2,480,000 / 2,720,000', 'Candidates: CNY 2,480,000 / 2,720,000 (Haipeng) / 2,576,513 (Mapai Jidian).'),
         ('227.9 / 248.12', 'Candidates: CNY 2.279 / 2.4812 / 2.295 million.'),
         ('3,040,000 / 3,580,000', 'Candidates: CNY 3,040,000 / 3,580,000 (Xin Dafang).'),
         ('3,167,000 / 3,030,000', 'Candidates: CNY 3,167,000 / 3,030,000 / 2,960,000.'),
         ('3,370,000 / 2,970,000', 'Candidates: CNY 3,370,000 / 2,970,000 / 2,545,000 (Xin Dafang).'),
         ('308 / 372', 'Candidates: CNY 3.08 / 3.72 (Wanshan) million. The quantity was confirmed in the "quantity" column '
                       'by comparing the pdftotext -layout and -raw outputs.'),
         ('325 / 309.36', 'Candidates: CNY 3.25 / 3.0936 / 3.34 million.'),
         ('340 / 316', 'Candidates: CNY 3.40 / 3.16 (Xin Dafang) million.'),
         ('中标者报价最高', 'Candidates: CNY 4,990,000 / 4,740,000 / 4,400,000; the winning bid was the highest.'),
         ('420.6 / 420', 'Candidates: CNY 4.206 / 4.20 / 4.05 million (…/jhwzb/644568.jhtml).'),
         ('496 / 457', 'Candidates: CNY 4.96 / 4.57 (Tianye Tonglian) / 4.8129 (Suzhou Dafang) million.'),
         ('流标', 'Candidates: CNY 5,120,000 / 5,200,000. The first tender of 2025-01 (320 t x 2 + 90 t x 1) failed '
                '(…/003001005/20250222/2d5adf2f-….html) and was re-tendered in two lots.'),
         ('810 / 714', 'Candidates: CNY 8.10 / 7.14 (Xin Dafang) million. Qualification: "at least 10 units completed and delivered".'),
         ('匹配方式同 A01', 'Matched as A01. Quantity verified from this notice. Candidate bids CNY 3.082 / 4.50 million (…/119273.htm).'),
         ('N4 的结果', 'Single candidate. Award result completed from this notice.'),
         ('380t（含）', 'Single candidate. Qualification: "at least 8 platform transporters of 380 t or more delivered".'),
         ('编号体系不同', 'Tender and award pages use different numbering; matched by project name ("150 t self-propelled hydraulic '
                    'platform trailer procurement, second call"), tenderer and agency. Candidate bids CNY 2.168 / 2.249 / 2.38 million.'),
         ('CSCMC-22305-27E', 'The tender text misprints the number as CSCMC-22305-27E; the page header gives CSCMC-23305-27E. '
                             'Candidates: CNY 2.79 / 2.80 / 2.738 million (…/jhwzb/445773.jhtml).'),
         ('主机转运', 'Stated use: "transfer of most main engines". Candidates: CNY 3,420,000 / 3,735,000.'),
         ('表格错行', 'The CSSC Chengxi (Taizhou) 200 t purchase. Other candidate bids: CNY 2,160,000 and 2,030,000 (table rows misaligned; bidder names not matched).'),
         ('分段建造能力提升', 'Project: "block construction capacity upgrade and intelligent retrofit". Unit price close to that of A16 '
                      '(also 450 t, 8/16), CNY 3.62 million. Candidates: CNY 3,770,000 / 3,760,000 / 3,150,000.')]
LINKS = [('）；结果', '); result'), ('招标（重新招标）', 'tender (re-tender) '), ('招标（第二次）', 'tender (second call) '),
         ('招标（重招）', 'tender (re-tender) '), ('；结果', '; result'), ('；中标', '; award'), ('（重发', '(reissued'),
         ('（首发', '(first issue'), ('；招标', '; tender'), ('招标', 'tender '), ('（', ' ('), ('）', ')')]
CJK = re.compile('[　-〿一-鿿＀-￯]')
MD = 'earlier_study/data/price_sources_R24.md'


def one(value, table, allow_none=False):
    hit = [en for key, en in table if key in value]
    assert len(hit) == 1 or (allow_none and not hit), (value, hit)
    return hit[0] if hit else ''


def amounts_ok(zh, en):
    """Every number of a Chinese note appears in its translation, or as a ten-thousand-yuan amount given in millions
    (internal record labels and section numbers of the working record are not carried over)."""
    def nums(t):
        return re.findall(r'\d[\d,]*(?:\.\d+)?', re.sub(r'[PN]\d|\d+\.\d+ 节', '', t))
    ens = nums(en)
    return all(n in ens or any(abs(float(m.replace(',', '')) * 100 - float(n.replace(',', ''))) < 1e-6 for m in ens)
               for n in nums(zh))


def links(t):
    for a, b in LINKS:
        t = t.replace(a, b)
    return re.sub(' +', ' ', t).strip()


def s1():
    t = (R.ROOT / MD).read_text(encoding='utf8')
    sec = t[t.index('### 1.1 A 类'):t.index('### 1.2')]
    parsed = {r['id']: r for r in R.records()}
    cluster = {b: 'B%02d' % (i + 1) for i, b in enumerate(sorted({r['buyer'] for r in parsed.values()}))}   # bootstrap order
    rows = []
    for line in sec.splitlines():
        if not line.startswith('| A'):
            continue
        c = [x.strip() for x in line.strip().strip('|').split('|')]
        rid = re.match(r'A\d\d', c[0]).group(0)
        p = parsed[rid]
        note = c[12] if len(c) > 12 else ''
        en = one(note, NOTES) if note else ''
        assert not note or amounts_ok(note, en), (rid, note, en)
        date = DATE.get(c[7], c[7])
        assert re.fullmatch(r'\d{4}-\d\d-\d\d( \(.*\))?', date), date
        rows.append({'id': rid, 'capacity_t': p['Q'], 'description': one(c[2], DESC), 'award_total_CNY_incl_VAT': c[3],
                     'amount_basis': AMOUNT[c[4]], 'quantity': p['qty'], 'unit_price_CNY_incl_VAT': round(p['unit']),
                     'unit_price_CNY_ex_VAT': round(p['unit'] / R.VAT), 'date': date, 'buyer': BUYER[p['buyer']],
                     'buyer_note': one(c[8], BUYER_NOTE, allow_none=True), 'buyer_cluster': cluster[p['buyer']],
                     'project_no': links(c[9]), 'announcements': links(c[10]), 'excerpt (original, Chinese)': c[11], 'notes': en})
    assert len(rows) == 33 and sum(r['quantity'] for r in rows) == 39, (len(rows), sum(r['quantity'] for r in rows))
    left = [(r['id'], k, v) for r in rows for k, v in r.items() if k != 'excerpt (original, Chinese)' and CJK.search(str(v))]
    assert not left, left
    return rows


def s2():
    p = json.loads((RES / 'price_curve.json').read_text(encoding='utf8'))
    p270 = p['p270_ex_vat']['affine']
    rows = []
    for (w, (wage, src)), hours in itertools.product(WAGES.items(), (2000, 2527)):
        for oc, n, i, days in itertools.product((0.30, 0.40), (8, 10, 15), (0.04, 0.06, 0.08), (250, 300)):
            crf = i / (1 - (1 + i) ** -n)
            rows.append(dict(wage_anchor=w, annual_wage_CNY=wage, annual_hours=hours, employer_oncost=oc, life_years=n, interest=i,
                             operating_days=days, capital_recovery_factor=round(crf, 6), p270_CNY_ex_VAT=round(p270),
                             daily_capital_CNY=round(p270 * crf / days, 2), hourly_labour_CNY=round(wage * (1 + oc) / hours, 2),
                             r_labour_hours_per_day=round(p270 * crf / days / (wage * (1 + oc) / hours), 3), wage_source=src))
        g = [x['r_labour_hours_per_day'] for x in rows if x['wage_anchor'] == w and x['annual_hours'] == hours]
        assert [round(min(g), 1), round(max(g), 1)] == p['r']['%s_%dh' % (w, hours)], (w, hours, min(g), max(g))
    return rows


def write(path, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == '__main__':
    has_md = (R.ROOT / MD).exists()                # the public release has Table S1 but not the working record
    a, b = (s1() if has_md else None), s2()
    if a:
        write(RES / 'S1_price_sources.csv', a)
    write(RES / 'S2_price_ratio.csv', b)
    sup = HERE.parents[1] / 'paper' / 'supplementary'          # files submitted with the manuscript
    if sup.parent.exists():
        import shutil
        sup.mkdir(exist_ok=True)
        shutil.copy2(RES / 'S1_price_sources.csv', sup / 'S1_price_sources.csv')
        shutil.copy2(RES / 'S2_price_ratio.csv', sup / 'S2_price_ratio.csv')
    print('S1: %s; S2: %d combinations; interval limits equal price_curve.json' % (
        '%d records (%d transporters)' % (len(a), sum(r['quantity'] for r in a)) if a else 'kept (no working record)', len(b)))
