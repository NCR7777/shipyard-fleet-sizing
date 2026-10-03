"""Single-batch instances for the exact comparison (directory `exact`): one release batch of a
main-study day. Seed s takes batch b = (s - 101) mod 8. All tasks of the batch (or the first n_max in
generation order), release and due shifted so that the batch is released at 0, empty-travel sub-matrix,
start positions unchanged (40 rows, a fleet uses the first K). The triangle inequality is recorded.
Study seeds 101-110 use the base files of the main study; trial seeds 9701-9703 are generated with fleet_scan.make_base.

  python exact_slices.py trial|study [n_max]      -> fleet_sizing/exact/slices/<cell>_s<seed>.json + index
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
EXACT_DIR = STUDY_ROOT / 'exact'
CELLS = ('jiang_short_baseline', 'jiang_massdep_baseline', 'rohcha_short_baseline', 'rohcha_massdep_baseline', 'liu_short_baseline', 'liu_massdep_baseline',
         'jiang_short_tight', 'liu_short_tight')
SEEDS = {'study': list(range(101, 111)), 'trial': [9701, 9702, 9703]}
COMMON = ('270', '300', '380', '425', '500', '550', 'MX1', 'MX2')


def families(cell):
    """Candidate set: 8 common families, plus L300_H425x1/x2 in the Liu-mass conditions (70 series)."""
    return COMMON + (('L300_H425x1', 'L300_H425x2') if cell.startswith('liu') else ())


def triangle_ok(d):
    T = d['tasks']
    n = len(T)
    D = [t['load'] + t['tauL'] + t['unload'] for t in T]
    tE, tE0 = d['tauE'], d['tauE_start']
    for x in range(n):
        for b in range(n):
            if b == x:
                continue
            via = D[x] + tE[x][b]
            if any(a != x and a != b and tE[a][b] > tE[a][x] + via for a in range(n)):
                return False
            if any(row[b] > row[x] + via for row in tE0):
                return False
    return True


def k_lb(d, fam, kmax=40):
    """Structural floor: smallest K (>= h + 1 for mixes, >= 1 otherwise) at which every
    block has a minimal flexible team (kappa from the slice). Same floor for every arm."""
    import fleet_scan
    fast_core = str(STUDY_ROOT / 'solver' / 'common')
    if fast_core not in sys.path:
        sys.path.insert(0, fast_core)
    from core import minimal_teams
    k0 = fleet_scan.kmin_of(fam) if fam.startswith(('L', 'MX')) else 1
    for K in range(k0, kmax + 1):
        cap = fleet_scan.caps_of(fam, K)
        if all(minimal_teams(cap, t['mass'], 'flex', d['meta']['max_team']) for t in d['tasks']):
            return K
    return None


def cut(day, seed, n_max=None):
    blen = day['meta']['batch_len_s']
    b = (seed - 101) % day['meta']['n_batches']
    idx = [i for i, t in enumerate(day['tasks']) if t['release'] == b * blen]
    if n_max:
        idx = idx[:n_max]
    off = b * blen
    tasks = [dict(day['tasks'][i], release=day['tasks'][i]['release'] - off, due=day['tasks'][i]['due'] - off) for i in idx]
    d = dict(name='%s_batch%d' % (day.get('name', 'day'), b), seed=seed, tasks=tasks, vehicles=day['vehicles'],
             tauE=[[day['tauE'][i][j] for j in idx] for i in idx],
             tauE_start=[[row[j] for j in idx] for row in day['tauE_start']], meta=dict(day['meta'], v1_batch=b, v1_n_max=n_max))
    return d, b


def base_path(cell, seed):
    import fleet_scan
    if seed >= 9000:
        return STUDY_ROOT / 'exact' / fleet_scan.make_base(STUDY_ROOT / 'exact', cell, seed)
    for sp in json.loads((STUDY_ROOT / 'main' / 'series.json').read_text(encoding='utf8')):
        if sp['cell'] == cell:
            return STUDY_ROOT / 'main' / sp['base'][str(seed)]
    raise KeyError(cell)


def main(kind, n_max=None):
    import fleet_scan
    fleet_scan._paper_path()
    out = EXACT_DIR / 'slices'
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for cell in CELLS:
        for seed in SEEDS[kind]:
            day = json.loads(base_path(cell, seed).read_text(encoding='utf8'))
            d, b = cut(day, seed, n_max)
            p = out / ('%s_s%d.json' % (cell, seed))
            p.write_text(json.dumps(d, separators=(',', ':')), encoding='utf8')
            index.append(dict(cell=cell, seed=seed, batch=b, n=len(d['tasks']), triangle_ok=triangle_ok(d),
                              heaviest=max(t['mass'] for t in d['tasks']), file=p.relative_to(EXACT_DIR).as_posix()))
    (EXACT_DIR / ('slices_%s.json' % kind)).write_text(json.dumps(index, indent=1) + '\n', encoding='utf8')
    print(json.dumps(dict(kind=kind, slices=len(index), n=sorted({r['n'] for r in index}),
                          triangle_ok=sum(r['triangle_ok'] for r in index))))


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
