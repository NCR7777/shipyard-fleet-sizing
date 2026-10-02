"""On-time targets of 90 % and 98 % (pooled on-time target), 120-min cap unchanged, for the 42 fleets of the fresh-day
confirmation set on the main days 101-130 (design file `supplementary_outage/design/service_level.json`).

Each series is the series of the main study (or of the delay-cap study at 120 min, `T120_*`) itself with a different
target: its stored runs are copied into the new study (same seeds and offsets, so a re-run would give identical
files) and the unchanged fleet_scan state machine continues the scan from them; only counts outside the stored range are
run. fleet_scan.py and fleet_scan_studies.py are not edited: the target is set by a Series subclass defined here (this file is
hashed into `SUPP2_FREEZE.json`). The subclass also skips the construction-only extension of the search-intensity
levels (it reports K_cp0 only and cannot change K*).

  python service_level.py prepare 90 | prepare 98      # -> service90/ or service98/ (98: structural screen first)
  python service_level.py plan 90                      # dry run: first wave of jobs
  pypy   service_level.py run 90 [workers]             #    restartable
  python service_level.py analyse [--preliminary]      # -> results/service90_fleets.csv, service98_fleets.csv (`S8p_*` from the
                                                    #    stored runs of the main results only)
  python service_level.py report [--preliminary]       # -> results/service_level_decisions.csv, service_level_report.json, service_level_report.md
"""
import json
import math
import shutil
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outage_service_common as C2                                      # noqa: E402

STUDY_ROOT, RES, SEEDS = C2.STUDY_ROOT, C2.RES, C2.SEEDS
CR = 0.10


def study_of(level):
    return STUDY_ROOT / ('service%s' % level)


def p_of(level):
    return {'90': 0.90, '98': 0.98}[level]


def prepare(level):
    import fleet_scan_studies as X
    P = C2.design('service_level.json')
    dst = study_of(level)
    if (dst / 'series.json').exists():
        sys.exit('%s already exists' % dst.name)
    src_specs = {}
    for stdy in ('main', 'delay_cap'):
        for sp in json.loads((STUDY_ROOT / stdy / 'series.json').read_text(encoding='utf8')):
            src_specs[stdy, sp['name']] = sp
    p = p_of(level)
    screen_rows, specs = [], []
    for it in P['series']:
        sp = dict(src_specs[it['study'], it['series']], service=p)
        if level == '98':
            sp['hi_limit'] = it['hi_limit_98']
            row = screen(STUDY_ROOT / it['study'], sp, p)
            screen_rows.append(row)
            if row['verdict'] != 'open':
                print('left out (screen %s): %s' % (row['verdict'], sp['name']))
                continue
        C2.copy_base(STUDY_ROOT / it['study'], dst, sp['base'])
        if (STUDY_ROOT / it['study'] / 'runs' / sp['name']).exists() and not (dst / 'runs' / sp['name']).exists():
            shutil.copytree(STUDY_ROOT / it['study'] / 'runs' / sp['name'], dst / 'runs' / sp['name'])
        specs.append(sp)
    if screen_rows:
        C2.write_csv(RES / 'service98_precheck.csv', screen_rows)
    X.fleet_scan.write_series(dst, specs)


def screen(study, sp, p):
    """structural_screen lower bounds with the allowance of target p."""
    import structural_screen as S
    import fleet_scan
    caps = fleet_scan.caps_of(sp['family'], S.KMAX)
    late = over = n = 0
    for s in SEEDS:
        d = json.loads((study / sp['base'][str(s)]).read_text(encoding='utf8'))
        lbs = S.bounds(d, caps)
        if lbs is None:
            return dict(series=sp['name'], verdict='structural', surely_late=None, surely_over=None, allowance=None)
        n += len(lbs)
        late += sum(x > 0 for x in lbs)
        over += sum(x > sp['tmax_s'] for x in lbs)
    allow = n - math.ceil(p * n - 1e-9)
    return dict(series=sp['name'], verdict='unattainable' if over or late > allow else 'open', surely_late=late, surely_over=over,
                allowance=allow)


def series_class():
    import fleet_scan_studies as X

    class ServiceSeries(X.Series):
        def __init__(self, spec, study, n_tasks=97):
            super().__init__(spec, study, n_tasks)
            self.need = math.ceil(spec['service'] * spec.get('n_total', n_tasks * len(X.fleet_scan.SEEDS)) - 1e-9)

        def qualifies(self, K, level=None):
            # The construction-only extension of the search-intensity levels (climb until the construction-only
            # checkpoint qualifies) only reports K_cp0 and cannot change K* = the smallest qualifying count; this study
            # skips it, which is the only use of a checkpoint level.
            return True if level is not None else super().qualifies(K)
    return X, ServiceSeries


def run(level, workers):
    X, ServiceSeries = series_class()
    study = study_of(level)
    C2.freeze_self(study, [__file__, HERE / 'outage_service_common.py'])
    X.fleet_scan.Series = ServiceSeries                       # parent process only; workers run fleet_scan.work unchanged
    X.run(study, workers)


def plan(level):
    """Dry run: the first wave of jobs the scan would submit from the copied runs (nothing is run or written)."""
    X, ServiceSeries = series_class()
    study = study_of(level)
    specs = json.loads((study / 'series.json').read_text(encoding='utf8'))
    tot = 0
    for sp in specs:
        S = ServiceSeries(sp, study)
        S.load()
        js = S.next_jobs() or []
        tot += len(js)
        if js:
            print('%-34s phase %-8s K %s: %d jobs' % (sp['name'], S.phase, sorted({j['K'] for j in js}), len(js)))
    print('first wave: %d jobs in %d series (later waves follow from their results)' % (tot, len(specs)))


# ------------------------------------------------------------------ analysis
def series_runs(level, names, preliminary):
    runs = C2.compact_runs(names)
    if not preliminary:
        for n in names:
            runs.setdefault(n, {}).update(C2.json_runs(study_of(level), n))
    return runs


def analyse_one(runs, p, kmin):
    import analyse_study as A
    nd = C2.need(p)
    complete = [k for k in sorted({k for (k, s, j) in runs}) if all((k, s, 0) in runs for s in SEEDS)]
    q = [k for k in complete if A.qualifies(runs, k, 'final', nd, SEEDS)]
    K = min(q) if q else None
    row = dict(K_final=K, tested=complete,
               determined=K is not None and (K - 1 < kmin or (K - 1 in complete and not A.qualifies(runs, K - 1, 'final', nd, SEEDS))),
               boundary_checked=K is not None and (K - 1 < kmin or all((K - 1, s, j) in runs for s in SEEDS for j in (1, 2))))
    if K is not None:
        ch = A.knapsack(runs, K, nd, SEEDS)
        n = len(SEEDS)
        row.update(on_time=sum(x[0] for x in ch) / C2.NTOT, crew_veh_h=sum(x[1] for x in ch) / n, crew_team_h=sum(x[2] for x in ch) / n,
                   after_h=sum(x[3] for x in ch) / n, coop_share=sum(x[4] for x in ch) / C2.NTOT, shift_h=64 * K)
    return row


def analyse(preliminary):
    P = C2.design('service_level.json')
    names = [it['series'] for it in P['series']]
    for level in ('90', '98'):
        if not preliminary and not (study_of(level) / 'series.json').exists():
            print('skip %s: not prepared' % level)
            continue
        included = set(names) if preliminary else {sp['name'] for sp in json.loads((study_of(level) / 'series.json').read_text(encoding='utf8'))}
        runs = series_runs(level, names, preliminary)
        rows = []
        for it in P['series']:
            r = dict(series=it['series'], cell=it['cell'], family=it['family'], service=p_of(level), K95=it['K95'])
            if it['series'] in included:
                r.update(analyse_one(runs.get(it['series'], {}), p_of(level), it['K_min']))
            else:
                r.update(K_final=None, note='screened out')
            rows.append(r)
        C2.write_csv(RES / ('%s_%s_fleets.csv' % ('service_level_preliminary' if preliminary else 'service_level', level)), rows)
        print(level, dict(Counter((r['K_final'] is not None, r.get('determined'), r.get('boundary_checked')) for r in rows)))


def report(preliminary):
    import csv
    import cost_decisions as RC
    tag = 'service_level_preliminary' if preliminary else 'service_level'
    P2 = json.loads((STUDY_ROOT / 'supplementary' / 'design' / 'fresh_days.json').read_text(encoding='utf8'))
    base = {}
    for cell, c in P2['conditions'].items():
        for p in c['predicted']:
            base[cell, p['model'], p['r'], p['labour']] = (p['winner'], p['coop'])
    rows, rep = [], {}
    for level in ('90', '98'):
        f = RES / ('%s_%s_fleets.csv' % (tag, level))
        if not f.exists():
            continue
        fl, coop, open_, flags = {}, {}, [], {}
        for r in csv.DictReader(open(f, encoding='utf-8-sig')):
            if r['K_final'] in ('', 'None'):
                open_.append(r['series'])
                continue
            k = (r['cell'], r['family'])
            fl[k] = dict(K=int(float(r['K_final'])), crew_veh_h=float(r['crew_veh_h']), crew_team_h=float(r['crew_team_h']),
                         after_h=float(r['after_h']))
            coop[k] = float(r['coop_share'])
            flags[k] = (r['determined'] == 'True', r['boundary_checked'] == 'True', int(float(r['K_final'])) - int(r['K95']))
        for cell in P2['conditions']:
            fams = [fm for (c, fm) in fl if c == cell]
            for m in RC.MAIN_MODELS:
                Pm = RC.proxy(m)
                for r in RC.main_r():
                    for lab in RC.LAB4:
                        cost = {fm: r * Pm(RC.caps(cell, fm, fl[cell, fm]['K'])) + RC.labour(fl[cell, fm], lab, fl[cell, fm]['K']) for fm in fams}
                        w = min(cost, key=cost.get) if cost else None
                        b = base[cell, RC.mname(m), round(r, 6), lab]
                        rows.append(dict(service=level, cell=cell, model=RC.mname(m), r=round(r, 6), labour=lab, winner=w,
                                         coop=coop.get((cell, w)), winner_95=b[0], coop_95=b[1], same=w == b[0]))
        g = [x for x in rows if x['service'] == level and x['winner']]
        ex = [x for x in g if not x['cell'].startswith('extraheavy')]
        rep[level] = dict(
            series_with_count=len(fl), series_without_count=open_,
            counts_not_determined=[k for k, v in flags.items() if not v[0]], boundary_missing=[k for k, v in flags.items() if not v[1]],
            dK_vs_95=dict(Counter(v[2] for v in flags.values())),
            P1_single_carry_outside_extraheavy=sum(x['coop'] <= CR for x in ex) / len(ex) if ex else None,
            P2_same_winner=sum(x['same'] for x in g) / len(g) if g else None,
            P2_by_condition={c: (lambda h: sum(x['same'] for x in h) / len(h) if h else None)([x for x in g if x['cell'] == c])
                             for c in P2['conditions']},
            P4_median_winner_coop_outside_extraheavy=st.median(x['coop'] for x in ex) if ex else None,
            P4_median_winner_coop_95_outside_extraheavy=st.median(x['coop_95'] for x in ex) if ex else None)
    rep = {k: dict(v, **({} if not preliminary else dict(note='preliminary: stored runs of the main results only')))
           for k, v in rep.items()}
    for k in rep:
        rep[k]['counts_not_determined'] = ['%s %s' % x for x in rep[k]['counts_not_determined']]
        rep[k]['boundary_missing'] = ['%s %s' % x for x in rep[k]['boundary_missing']]
    C2.write_csv(RES / ('%s_decisions.csv' % tag), rows)
    (RES / ('%s_report.json' % tag)).write_text(json.dumps(rep, indent=1) + '\n', encoding='utf8')
    md = ['# On-time target%s' % (' (preliminary, stored runs of the main results only)' if preliminary else ''), '',
          '| level | single carry outside the extra-heavy scenario | same winner as 95 % '
          '| median winner coupling, outside the extra-heavy scenario | dK vs 95 % |',
          '| --- | --- | --- | --- | --- |']
    for k, v in rep.items():
        md.append('| %s %% | %.1f %% | %.1f %% | %.2f %% (95 %%: %.2f %%) | %s |' % (
            k, 100 * v['P1_single_carry_outside_extraheavy'], 100 * v['P2_same_winner'], 100 * v['P4_median_winner_coop_outside_extraheavy'],
            100 * v['P4_median_winner_coop_95_outside_extraheavy'], v['dK_vs_95']))
    (RES / ('%s_report.md' % tag)).write_text('\n'.join(md) + '\n', encoding='utf8')
    print('\n'.join(md))
    print(json.dumps(rep, indent=1))


if __name__ == '__main__':
    a = sys.argv[1:]
    pre = '--preliminary' in a
    a = [x for x in a if not x.startswith('--')]
    if a[0] == 'prepare':
        prepare(a[1])
    elif a[0] == 'plan':
        plan(a[1])
    elif a[0] == 'run':
        run(a[1], int(a[2]) if len(a) > 2 else 8)
    elif a[0] == 'analyse':
        analyse(pre)
    elif a[0] == 'report':
        report(pre)
