"""Second case: published data of Liu, Yin & Khan 2022 (PLOS ONE 17(3):e0265047).

Data (checked against the paper and its page images):
  - tasks: S1 Data (pone.0265047.s001.xlsx), 50 tasks: task number, block number, origin, destination, start time,
    latest time, mass (t);
  - fleet: Table 4 of the paper (PDF p.12): 250, 270, 320, 380, 420 t;
  - distances: Table 5 of the paper (PDF p.12), 8 × 8 (m); stockyard 5 → coating center is 130 m and 90 m in
    reverse, so the table is asymmetric; it is used as printed;
  - speeds: §4.1.1, loaded 30 m/min, empty 50 m/min; load and unload 10 min each (§4.1.1 item 4);
  - time window: [start time st_i, expected arrival at_i]; completion after at_i counts as delay (§3 objective f3),
    the same delivery measure as ours;
  - working day of 600 min starting at 8:00 (§4.1.1 item 1).
Assumptions (not given in the paper; stated in the manuscript):
  - the time axis counts working time only: day d, hh:mm maps to (d − 1) × 600 + (hh·60 + mm − 480) min, i.e. there
    is no work at night and the clock stops;
  - the depot location is not given (Table 5 has no depot): by default each vehicle starts at the origin of its first
    task (no empty travel); the sensitivity case starts all vehicles at one site (start_site argument); the return
    trip to the depot (term d_ke of the paper) is not counted;
  - no coupling (assumption 1 and Eq. (8) of the paper): the largest vehicle (420 t) can carry the heaviest block
    (399 t), so our "coupling only when overweight" rule (rigid) means no coupling here.
Usage:
  python liu_data.py [--xlsx path]   → instances/liu/liu2022.json
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
import params as P               # noqa: E402
from core import load_index      # noqa: E402

PAPER = os.path.normpath(os.path.join(HERE, '..', '..'))
XLSX = os.path.normpath(os.path.join(PAPER, '..', 'pone.0265047.s001.xlsx'))
SITES = ['stockyard No.1', 'stockyard No.2', 'stockyard No.3', 'stockyard No.4', 'stockyard No.5',
         'Pre-treatment center', 'Pre-outfitting center', 'Coating center']
DIST = [  # Table 5 (m), row = from, column = to; '-' taken as 0
    [0, 295, 680, 550, 710, 40, 225, 610],
    [295, 0, 525, 425, 585, 255, 70, 455],
    [680, 525, 0, 160, 200, 640, 455, 70],
    [550, 425, 160, 0, 160, 480, 355, 90],
    [710, 585, 200, 160, 0, 640, 515, 130],
    [40, 255, 640, 480, 640, 0, 185, 570],
    [225, 70, 455, 355, 515, 185, 0, 385],
    [610, 455, 70, 90, 90, 570, 385, 0],
]
FLEET_LIU2022 = [250, 270, 320, 380, 420]
V_LOADED = 30.0 / 60      # m/s
V_EMPTY = 50.0 / 60
HANDLE_S = 600
DAY_MIN = 600


def site_index(s):
    s = re.sub(r'\s+', ' ', str(s)).strip().lower()
    for k, name in enumerate(SITES):
        if s == name.lower():
            return k
    raise ValueError('unknown site: %r' % s)


def work_minutes(s):
    """'Day 2 16:00' → (2 − 1) × 600 + (16 × 60 − 480). A full-width colon is read as an ASCII colon."""
    m = re.match(r'Day\s*(\d+)\s*(\d+)\s*[:：]\s*(\d+)', str(s).strip())
    if not m:
        raise ValueError('unrecognised time: %r' % s)
    d, hh, mm = map(int, m.groups())
    return (d - 1) * DAY_MIN + hh * 60 + mm - 480


def read_tasks(xlsx=XLSX):
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(min_row=3, values_only=True))
    tasks = []
    for r in rows:
        if r[0] is not None:
            tasks.append([x for x in r])
        elif tasks and any(v is not None for v in r):        # site name over two rows ('Stockyard' / 'No.1')
            for j, v in enumerate(r):
                if v is not None:
                    tasks[-1][j] = (str(tasks[-1][j]) + ' ' + str(v)).strip()
    return tasks


def make_case(caps=FLEET_LIU2022, start_site=None, xlsx=XLSX, name='liu2022', crew_team=None):
    raw = read_tasks(xlsx)
    tasks = []
    for t in raw:
        o, d = site_index(t[2]), site_index(t[3])
        rel, due = 60 * work_minutes(t[4]), 60 * work_minutes(t[5])
        tl = int(round(DIST[o][d] / V_LOADED))
        tasks.append(dict(id='L%02d' % int(t[0]), block=int(t[1]), o=SITES[o], d=SITES[d], o_idx=o, d_idx=d,
                          mass=int(t[6]), release=rel, due=due, load=HANDLE_S, unload=HANDLE_S, tauL=tl,
                          batch=int(rel // (60 * DAY_MIN))))
    n = len(tasks)
    tE = [[0 if i == j else int(round(DIST[tasks[i]['d_idx']][tasks[j]['o_idx']] / V_EMPTY)) for j in range(n)]
          for i in range(n)]
    if start_site is None:
        tE0 = [[0] * n for _ in caps]
    else:
        s = site_index(start_site)
        tE0 = [[int(round(DIST[s][t['o_idx']] / V_EMPTY)) for t in tasks] for _ in caps]
    inst = dict(name=name, seed=None, tasks=tasks,
                vehicles=[dict(id='V%d' % (k + 1), cap=c, start=start_site or 'first-task origin') for k, c in enumerate(caps)],
                tauE_start=tE0, tauE=tE,
                meta=dict(delta_s=60 * P.DELTA_MIN, crew=P.CREW, max_team=P.MAX_TEAM, crew_team=crew_team,
                          source='Liu, Yin & Khan 2022, PLOS ONE 17(3):e0265047, S1 Data + Tables 4-5',
                          v_empty_mps=V_EMPTY, v_loaded_mps=V_LOADED, time_axis='work minutes (600 min/day, nights skipped)',
                          time_unit='s', start_site=start_site))
    e = sum(tE[i][j] for i in range(n) for j in range(n) if i != j) / (n * (n - 1))
    inst['meta']['load_index'] = load_index(list(caps), [t['mass'] for t in tasks],
                                            [t['load'] + t['tauL'] + t['unload'] for t in tasks],
                                            60 * P.DELTA_MIN, e, P.MAX_TEAM, H=5 * DAY_MIN * 60.0)
    return inst


if __name__ == '__main__':
    x = sys.argv[sys.argv.index('--xlsx') + 1] if '--xlsx' in sys.argv else XLSX
    d = make_case(xlsx=x)
    out = os.path.join(PAPER, 'instances', 'liu', d['name'] + '.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(d, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    T = d['tasks']
    print('%d tasks; masses %d–%d t; fleet %s; load %s' % (len(T), min(t['mass'] for t in T), max(t['mass'] for t in T),
                                                FLEET_LIU2022, {k: round(v, 3) if isinstance(v, float) else v
                                                            for k, v in d['meta']['load_index'].items()}))
    print('mean loaded travel %.1f min; load and unload %d min each; time-window lengths %s min' % (
        sum(t['tauL'] for t in T) / len(T) / 60, HANDLE_S // 60,
        sorted(set((t['due'] - t['release']) // 60 for t in T))))
