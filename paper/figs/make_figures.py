"""Figures and tables of the manuscript. Reads only the result files in `fleet_sizing/results`.

  python paper/figs/make_figures.py
    -> latex/figs/fig_winners.pdf/.png, fig_search.pdf/.png
       latex/tables/kstar_main.tex, case_scratch.tex, case_additions.tex
Times New Roman is required (as make_manuscript_figures.py).
"""
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib import font_manager as fm                          # noqa: E402
from matplotlib.patches import Patch, Rectangle                    # noqa: E402

HERE = Path(__file__).resolve().parent
PAPER = HERE.parent
ROOT = PAPER.parent
RES = ROOT / 'fleet_sizing' / 'results'
OUT = PAPER / 'latex' / 'figs'
TAB = PAPER / 'latex' / 'tables'
OUT.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'fleet_sizing' / 'code'))
import cost_decisions as C                                              # noqa: E402

fm.findfont('Times New Roman', fallback_to_default=False)
plt.rcParams.update({'font.family': 'Times New Roman', 'font.size': 8.5, 'axes.titlesize': 9, 'axes.labelsize': 8.5,
                     'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 8, 'axes.linewidth': 0.6,
                     'pdf.fonttype': 42, 'ps.fonttype': 42, 'mathtext.fontset': 'custom', 'mathtext.rm': 'Times New Roman',
                     'mathtext.it': 'Times New Roman:italic', 'hatch.linewidth': 0.5, 'savefig.facecolor': 'white'})
W = 180 / 25.4
COL = {'200': '#f0f0f0', '250': '#d9d9d9', '270': '#c6dbef', '300': '#a9c8e1', '325': '#56b4b8', '380': '#4388b5',
       '425': '#183a63', '500': '#91679d', '550': '#cc6d24', 'MX1': '#b9d7bf', 'MX2': '#42835a'}
DARK = {'425', '380', '500', '550', 'MX2', '325'}
NAME = {k: k + ' t' for k in COL}
NAME.update(MX1='1 heavy + 270 t', MX2='2 heavy + 270 t')
MS = [('jiang', 'Jiang'), ('lightskew', 'Light-skewed'), ('uniform', 'Uniform'), ('extraheavy', 'Extra-heavy'), ('rohcha', 'Roh–Cha'), ('liu', 'Liu')]
HS = [('short', 'short'), ('massdep', 'mass-dep.'), ('long', 'long')]
DS = [('baseline', 'base'), ('tight', 'tight')]
FAMS = ['200', '250', '270', '300', '325', '380', '425', '500', '550', 'MX1', 'MX2']


def rcsv(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def cells():
    return [('%s_%s_%s' % (m, h, d), '%s, %s, %s' % (mn, hn, dn)) for m, mn in MS for h, hn in HS for d, dn in DS]


def fig_winners():
    fl = {(r['cell'], r['family']): r for r in rcsv(RES / 'main_fleets.csv')}
    dec = [x for x in rcsv(RES / 'main_decisions.csv') if x['model'] == 'affine']
    boot = {(x['cell'], x['labour'], round(float(x['r']), 6)): float(x['support']) for x in rcsv(RES / 'bootstrap_decisions.csv') if x['model'] == 'affine'}
    grade = {(x['cell'], x['labour'], round(float(x['r']), 6)): x['grade'] for x in rcsv(RES / 'grading_decisions.csv') if x['model'] == 'affine'}
    rs = C.main_r()
    cl = cells()
    fig = plt.figure(figsize=(W, 6.9))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1.05], wspace=0.1, left=0.175, right=0.925, top=0.955, bottom=0.165)
    used = set()
    for p, (lab, title) in enumerate((('shift_h', '(a) Shift staffing'), ('crew_team_h', '(b) Operating crew per team'))):
        ax = fig.add_subplot(gs[0, p])
        w = {(x['cell'], round(float(x['r']), 6)): x['winner'] for x in dec if x['labour'] == lab}
        for i, (cell, _) in enumerate(cl):
            for j, r in enumerate(rs):
                f = w[cell, round(r, 6)]
                used.add(f)
                y = len(cl) - 1 - i
                ax.add_patch(Rectangle((j, y), 1, 1, facecolor=COL[f], edgecolor='white', lw=0.4))
                share = float(fl[cell, f]['coop_share'])
                ax.text(j + 0.5, y + 0.5, '%d' % round(100 * share), ha='center', va='center', fontsize=5.6,
                        color='white' if f in DARK else 'black')
                if boot.get((cell, lab, round(r, 6)), 1.0) < 0.8:
                    ax.add_patch(Rectangle((j, y), 1, 1, fill=False, hatch='////', edgecolor='#555555', lw=0))
                if grade.get((cell, lab, round(r, 6))) == 'weak':
                    ax.plot(j + 0.88, y + 0.82, marker='o', ms=1.8, color='#d62728')
        ax.set_xlim(0, len(rs))
        ax.set_ylim(0, len(cl))
        ax.set_xticks([j + 0.5 for j in range(len(rs))])
        ax.set_xticklabels(['%.1f' % r for r in rs], rotation=90, fontsize=6.5)
        ax.set_xlabel('Price ratio $r$ (labour-hours/day)')
        ax.set_yticks([len(cl) - 1 - i + 0.5 for i in range(len(cl))])
        ax.set_yticklabels([n for _, n in cl] if p == 0 else [], fontsize=6)
        ax.tick_params(length=0)
        ax.set_title(title, loc='left')
        for s in ax.spines.values():
            s.set_visible(False)
    # (c) mechanism: coupled service share vs cost premium over the cell's cheapest (affine, r = 12.4, shift)
    ax = fig.add_subplot(gs[0, 2])
    mech = json.loads((RES / 'claim_numbers.json').read_text(encoding='utf8'))['per_series']
    P = C.proxy(('affine',))
    rm = rs[4]
    cost = {k: rm * P(C.caps(k[0], k[1], int(v['K_final']))) + 64 * int(v['K_final']) for k, v in fl.items()}
    best = {c: min(v for k, v in cost.items() if k[0] == c) for c, _ in cl}
    for f in FAMS:
        xs = [100 * mech['%s_%s' % k]['coop_service_share'] for k in fl if k[1] == f]
        ys = [100 * (cost[k] / best[k[0]] - 1) for k in fl if k[1] == f]
        ax.scatter(xs, ys, s=7, color=COL[f], edgecolor='#333333', linewidth=0.25, label=NAME[f], zorder=3)
    ax.set_xlabel('Coupled share of service time (%)')
    ax.set_ylabel('Cost above the cheapest fleet (%)', labelpad=1)
    ax.yaxis.set_label_position('right')
    ax.yaxis.tick_right()
    ax.set_title('(c) Coupling and cost, $r$ = %.1f, shift' % rm, loc='left')
    ax.grid(color='#e5e5e5', lw=0.4, zorder=0)
    handles = [Patch(facecolor=COL[f], edgecolor='#999999', lw=0.3, label=NAME[f]) for f in FAMS]
    handles += [Patch(facecolor='white', edgecolor='#555555', hatch='////', lw=0.3, label='Winner support < 80% in day resampling'),
                plt.Line2D([], [], marker='o', ms=3, color='#d62728', lw=0, label='Weak search dependence')]
    fig.legend(handles=handles, loc='lower center', ncol=5, frameon=False, fontsize=6.8, bbox_to_anchor=(0.55, 0.0))
    for ext in ('pdf', 'png'):
        fig.savefig(OUT / ('fig_winners.' + ext), dpi=300)
    plt.close(fig)


def fig_search():
    lv = rcsv(RES / 'main_search_levels.csv')
    fin = {(x['cell'], x['model'], x['r']): x['winner'] for x in rcsv(RES / 'main_decisions.csv') if x['labour'] == 'shift_h'}
    levels = [('greedy', 'Greedy'), ('cp0', 'Constr.'), ('cp100', '100 it.'), ('cp300', '300 it.'), ('single', '786 it.'),
              ('final', 'Final')]
    agree = [65.4, 69.4, 74.7, 88.0, 94.4, 100.0]                  # `main_summary.md` section 7 (checked below)
    fig, axs = plt.subplots(1, 3, figsize=(W, 2.5), gridspec_kw=dict(width_ratios=[1.25, 1.25, 1], wspace=0.35),
                            constrained_layout=False)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.8, bottom=0.2)
    ax = axs[0]
    ax.plot(range(6), agree, marker='o', color='#183a63', lw=1.2)
    for i, a in enumerate(agree):
        ax.text(i, a + 2, '%.0f' % a, ha='center', fontsize=7)
    ax.set_xticks(range(6))
    ax.set_xticklabels([n for _, n in levels], fontsize=6.8)
    ax.set_ylim(55, 106)
    ax.set_ylabel('Same fleet as final (%)')
    ax.set_title('(a) Purchase agreement, 1,620 settings', loc='left')
    ax.grid(axis='y', color='#e5e5e5', lw=0.4)
    ax = axs[1]
    kf = {x['series']: int(x['K_final']) for x in lv}
    bot = [0] * 6
    for d, lab, col in ((0, 'Same count', '#c6dbef'), (1, 'One more', '#4388b5'), (2, 'Two or more', '#183a63')):
        v = []
        for lev, _ in levels:
            dk = [int(x['K_' + lev]) - kf[x['series']] for x in lv]
            v.append(sum((k == d) if d < 2 else (k >= 2) for k in dk))
        ax.bar(range(6), v, bottom=bot, color=col, label=lab, width=0.7)
        bot = [a + b for a, b in zip(bot, v)]
    ax.set_xticks(range(6))
    ax.set_xticklabels([n for _, n in levels], fontsize=6.8)
    ax.set_ylabel('Fleet series')
    ax.set_title('(b) Count relative to $K^*$, 384 series', loc='left', pad=15)
    ax.legend(frameon=False, fontsize=6.3, loc='lower center', ncol=3, bbox_to_anchor=(0.5, 1.0), handlelength=1.2, columnspacing=0.8)
    ax = axs[2]
    lr = rcsv(RES / 'main_load_rule.csv')
    for due, lab, col, off in (('baseline', 'Baseline due dates', '#a9c8e1', -0.2), ('tight', 'Tight due dates', '#cc6d24', 0.2)):
        d = [int(x['d']) for x in lr if x['cell'].endswith(due) and x['d'] not in ('', 'None')]
        xs = sorted(set(range(-1, 6)))
        ax.bar([x + off for x in xs], [d.count(x) for x in xs], width=0.4, color=col, label=lab)
    ax.set_xlabel(r'$K^*-K_\rho$ (transporters)')
    ax.set_ylabel('Fleet series')
    ax.set_title('(c) Load-based sizing error', loc='left')
    ax.legend(frameon=False, fontsize=6.5)
    for ext in ('pdf', 'png'):
        fig.savefig(OUT / ('fig_search.' + ext), dpi=300)
    plt.close(fig)
    # the plotted agreement values must equal the recomputed ones
    import report_main as R
    fr = rcsv(RES / 'main_fleets.csv')
    wf = R.winners(R.fleets_at(fr, 'final'), C.MAIN_MODELS, C.main_r(), ('shift_h',))
    for (lev, _), a in zip(levels, agree):
        wl = R.winners(R.fleets_at(fr, lev), C.MAIN_MODELS, C.main_r(), ('shift_h',))
        assert abs(100 * sum(wl[k] == v for k, v in wf.items()) / len(wf) - a) < 0.05, lev


def tab_kstar():
    fl = {(r['cell'], r['family']): r for r in rcsv(RES / 'main_fleets.csv')}
    L = [r'\begin{table}', r'\centering\small',
         r"\caption{Service-qualified counts $K^*$ at baseline due dates (30 daily instances; at least 95\% of blocks on time and no block more than 120~min late). Mixes contain one or two heavy members (550~t in the search; priced as 500~t for Jiang, light-skewed and uniform masses and as 425~t for Liu masses) and 270~t light members. ``--'': no feasible team for the heaviest blocks ($\kappa=3$). $^{\dagger}$: boundary check stopped after two lowering rounds (Appendix~\ref{app:verification}).}",
         r'\label{tab:kstar}', r'\fitmanuscripttable{\begin{tabular}{ll' + 'c' * 11 + '}', r'\toprule',
         r' & & \multicolumn{9}{c}{Homogeneous tier (t)} & \multicolumn{2}{c}{Mix} \\', r'\cmidrule(lr){3-11}\cmidrule(lr){12-13}',
         'Masses & Handling & ' + ' & '.join(FAMS[:9]) + r' & 1 heavy & 2 heavy \\', r'\midrule']
    for i, (m, mn) in enumerate(MS):
        for h, hn in HS:
            cell = '%s_%s_baseline' % (m, h)
            vals = []
            for f in FAMS:
                r = fl.get((cell, f))
                vals.append('--' if r is None else r['K_final'] + (r'$^{\dagger}$' if r['boundary_checked'] != 'True' else ''))
            L.append('%s & %s & %s \\\\' % (mn if h == 'short' else '', hn.capitalize(), ' & '.join(vals)))
        if i < len(MS) - 1:
            L.append(r'\addlinespace')
    L += [r'\bottomrule', r'\end{tabular}}', r'\end{table}']
    (TAB / 'kstar_main.tex').write_text('\n'.join(L) + '\n', encoding='utf8')


def tab_case():
    sc = rcsv(RES / 'second_case_scratch.csv')
    P = C.proxy(('affine',))
    L = [r'\begin{table}', r'\centering\small',
         r'\caption{Second yard, fleets sized from scratch \citep{liu2022}: 30 daily instances per workload multiple $k$, same service specification and scan as the main case, 10-h shift. Capital proxy: affine price curve relative to one 270~t transporter; shift staffing: $4\times10$ crew-hours per transporter and day. $^{*}$: target met only with work after the 10-h shift.}',
         r'\label{tab:case}', r'\fitmanuscripttable{\begin{tabular}{l' + 'c' * 11 + '}', r'\toprule',
         ' & ' + ' & '.join(f if not f.startswith('MX') else ('1 heavy' if f == 'MX1' else '2 heavy') for f in FAMS) + r' \\', r'\midrule']
    for k in ('6', '8'):
        rows = {x['type']: x for x in sc if x['k'] == k}
        L.append(r'$k=%s$: $K^*$ & ' % k + ' & '.join(rows[f]['K'] + (r'$^{*}$' if rows[f]['needs_after_shift'] == 'True' else '') for f in FAMS) + r' \\')
        L.append(r'\quad capital proxy & ' + ' & '.join('%.2f' % float(rows[f]['capital_proxy']) for f in FAMS) + r' \\')
    L += [r'\bottomrule', r'\end{tabular}}', r'\end{table}']
    (TAB / 'case_scratch.tex').write_text('\n'.join(L) + '\n', encoding='utf8')
    ad = rcsv(RES / 'second_case_additions.csv')
    L = [r'\begin{table}', r'\centering\small',
         r"\caption{Second yard: transporters added to the published fleet (250, 270, 320, 380 and 420~t) to meet the service specification, by workload multiple $k$, added type and coupling rule \citep{liu2022}. ``--'': not met within four additions. $^{\dagger}$: on at least one day, work after the 10-h shift exceeded 5\% of the available transporter time; $^{*}$: met only with work after the shift.}",
         r'\label{tab:case-add}', r'\fitmanuscripttable{\begin{tabular}{lcccccccc}', r'\toprule',
         r' & \multicolumn{4}{c}{Without coupling} & \multicolumn{4}{c}{With flexible coupling} \\', r'\cmidrule(lr){2-5}\cmidrule(lr){6-9}',
         r'$k$ & 250~t & 270~t & 380~t & 420~t & 250~t & 270~t & 380~t & 420~t \\', r'\midrule']
    for k in ('1', '2', '4', '6', '8'):
        v = []
        for rule in ('nocoup', 'flex'):
            for X in ('250', '270', '380', '420'):
                x = next(r for r in ad if r['k'] == k and r['rule'] == rule and r['X'] == X)
                if x['n_star'] in ('', 'None'):
                    v.append('--')
                else:
                    v.append(x['n_star'] + (r'$^{\dagger}$' if float(x['after_share_max'] or 0) > 0.05 else '') +
                             (r'$^{*}$' if x['meets_shift_hard'] != 'True' else ''))
        L.append('%s & %s \\\\' % (k, ' & '.join(v)))
    L += [r'\bottomrule', r'\end{tabular}}', r'\end{table}']
    (TAB / 'case_additions.tex').write_text('\n'.join(L) + '\n', encoding='utf8')


def fig_tmax():
    """Delay-cap axis under shift staffing (`delay_cap_grid.csv`): coupled share of the cheapest fleet and its cost relative to
    the uncapped cheapest fleet, over the 45 price settings (5 price models x 9 r) of each mass scenario."""
    g = [x for x in rcsv(RES / 'delay_cap_grid.csv') if x['labour'] == 'shift_h']
    levels = [('inf', 'None'), ('480', '480'), ('240', '240'), ('120', '120'), ('60', '60'), ('30', '30')]
    masses = [('jiang_short_baseline', 'Jiang', '#183a63', 'o'), ('uniform_short_baseline', 'Uniform', '#4388b5', 's'), ('liu_short_baseline', 'Liu', '#cc6d24', '^')]
    fig, axs = plt.subplots(1, 2, figsize=(W, 2.3))
    fig.subplots_adjust(left=0.07, right=0.99, top=0.86, bottom=0.2, wspace=0.28)
    axs[0].axhline(10, color='#888888', lw=0.7, ls='--', zorder=0)
    axs[0].text(5.1, 10.3, 'one block in ten', ha='right', va='bottom', fontsize=6.8, color='#666666')
    for k, (cell, lab, col, mk) in enumerate(masses):
        off = (k - 1) * 0.12                                               # side by side in panel (b)
        coop, med, lo, hi = [], [], [], []
        for lev, _ in levels:
            s = [x for x in g if x['cell'] == cell and x['level'] == lev]
            cs = {round(float(x['coop']), 6) for x in s}
            assert len(s) == 45 and len(cs) == 1, (cell, lev, cs)            # one cheapest fleet per cap under shift staffing
            coop.append(100 * cs.pop())
            cv = sorted(100 * float(x['cost_vs_inf']) for x in s)
            med.append(cv[len(cv) // 2]), lo.append(cv[0]), hi.append(cv[-1])
        axs[0].plot(range(6), coop, marker=mk, color=col, lw=1.1, ms=3.5, label=lab)
        xs = [i + off for i in range(6)]
        axs[1].vlines(xs, lo, hi, color=col, lw=1.0)
        axs[1].plot(xs, med, marker=mk, color=col, lw=0, ms=3.5, label=lab)
    for ax, ttl, yl in ((axs[0], '(a) Blocks coupled by the cheapest fleet', 'Coupled blocks (%)'),
                        (axs[1], '(b) Daily cost relative to no cap', 'Cost increase (%)')):
        ax.set_xticks(range(6))
        ax.set_xticklabels([n for _, n in levels])
        ax.set_xlabel(r'Per-block delay cap $T_{\max}$ (min)')
        ax.set_ylabel(yl)
        ax.set_title(ttl, loc='left')
        ax.grid(axis='y', color='#e5e5e5', lw=0.4)
    axs[0].legend(frameon=False, fontsize=7)
    for ext in ('pdf', 'png'):
        fig.savefig(OUT / ('fig_tmax.' + ext), dpi=300)
    plt.close(fig)


if __name__ == '__main__':
    fig_winners()
    fig_search()
    fig_tmax()
    tab_kstar()
    tab_case()
    print('written')
