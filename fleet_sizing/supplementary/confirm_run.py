"""Prepare and run the supplementary studies with the unchanged machinery of the main study: fresh-day confirmation
(directory `fresh_days`), slow speed and long handling (directories `unresolved_scan`, `unresolved_scan`, ..., `candidates_speed`, `candidates_handling`) and extended
light-heavy mixes in 13 further conditions (directory `extended_mixes`).

fleet_scan.py and fleet_scan_studies.py are imported unchanged (fleet_scan.run writes and checks a file-integrity record of each study,
`FREEZE.json`, as for every study); series definitions come only from the design files in `supplementary/design`.

  python confirm_run.py prepare-fresh-days  fresh_days      # fresh days 601-630, fleet sets and K_start from fresh_days.json
  python confirm_run.py prepare-extended-mixes  extended_mixes      # extended mixes in 13 conditions (extended_mixes.json), days 101-130
  python confirm_run.py prepare-unresolved unresolved_scan [family ...]   # part A: open one-factor series, hi_limit 40, runs copied
                                                   # (after `structural_screen.py sensitivity ...`); later batches: `unresolved_scan`, `unresolved_scan3`, ...
  python confirm_run.py prepare-candidates candidates_speed     # part B: 425/500 t and mixes at slow speeds; conditions still
                                         # waiting for a part-A count are skipped and go into `candidates_handling` later
  python confirm_run.py run <study> [workers]
  python confirm_run.py status <study>
"""
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY_ROOT = HERE.parent
ROOT = STUDY_ROOT.parent
sys.path.insert(0, str(STUDY_ROOT / 'code'))
import compat                                             # noqa: E402,F401  (psutil priority constant off Windows)
import fleet_scan_studies as X                                     # noqa: E402
fleet_scan = X.fleet_scan
PRE = HERE / 'design'


def design(name):
    return json.loads((PRE / name).read_text(encoding='utf8'))


SEED_RE = re.compile(r'(?:^|_)s(\d+)(?:_j\d+)?\.json$')


def used_seeds():
    """Instance seeds in use anywhere under the project root: base/run file names and series.json seed lists."""
    seen = set()
    for p in ROOT.rglob('*.json'):
        m = SEED_RE.search(p.name)
        if m:
            seen.add(int(m.group(1)))
        elif p.name == 'series.json':
            try:
                for sp in json.loads(p.read_text(encoding='utf8')):
                    seen.update(int(s) for s in sp.get('seeds', []))
                    seen.update(int(s) for s in sp.get('base', {}) if str(s).isdigit())
            except (ValueError, AttributeError, TypeError):
                pass
    return seen


def assert_fresh(seeds, study):
    clash = sorted(set(seeds) & used_seeds())
    if clash and not (STUDY_ROOT / study / 'series.json').exists():
        sys.exit('seeds already used elsewhere in the project: %s - choose another block of seeds before '
                 'writing the design file' % clash[:10])


def same_as(study, ref):
    """Base files generated for this study must equal those of the reference study (same cell, gen, seed)."""
    diff = [p.name for p in (STUDY_ROOT / study / 'base').glob('*.json')
            if (STUDY_ROOT / ref / 'base' / p.name).exists() and (STUDY_ROOT / ref / 'base' / p.name).read_bytes() != p.read_bytes()]
    assert not diff, ('base instances differ from %s' % ref, diff[:5])
    return sum((STUDY_ROOT / ref / 'base' / p.name).exists() for p in (STUDY_ROOT / study / 'base').glob('*.json'))


def prepare_fresh_days(study):
    P = design('fresh_days.json')
    assert_fresh(P['seeds'], study)
    items = [('fresh_%s_%s' % (cell, f), cell, f, None, v['K_start']) for cell, c in P['conditions'].items() for f, v in c['families'].items()]
    X.build(STUDY_ROOT / study, items, P['seeds'], P['seed_offset'])


def prepare_extended_mixes(study):
    P = design('extended_mixes.json')
    items = [('extmix_%s_%s' % (cell, f), cell, f, None, v['K_start']) for cell, c in P['conditions'].items() for f, v in c['families'].items()]
    X.build(STUDY_ROOT / study, items, P['seeds'], P['seed_offset'])
    print('base files identical to main:', same_as(study, 'main'))


def prepare_unresolved(study, families=()):
    """Open series of the one-factor sensitivity study with hi_limit 40 and their runs. Series that the structural
    screen (results/sensitivity_precheck.csv) shows unattainable are left out (they are reported as such);
    optional family filter, e.g. `prepare-unresolved unresolved_scan 550 MX2` to run the likely winners first."""
    import csv
    P = design('slow_handling.json')['part_a']
    pc = STUDY_ROOT / 'results' / 'sensitivity_precheck.csv'
    if not pc.exists():
        sys.exit('run the structural screen first: python structural_screen.py sensitivity ' + ' '.join(P['series']))
    verdict = {r['series']: r['verdict'] for r in csv.DictReader(open(pc, encoding='utf-8-sig'))}
    src = STUDY_ROOT / 'sensitivity'
    dst = STUDY_ROOT / study
    fresh_study(dst)
    sensitivity = {sp['name']: sp for sp in json.loads((src / 'series.json').read_text(encoding='utf8'))}
    done = taken('unresolved_scan')
    specs = []
    for name in P['series']:
        if name in done:
            continue
        if verdict.get(name) != 'open':
            print('left out: %s (screen: %s)' % (name, verdict.get(name, 'not screened')))
            continue
        if families and sensitivity[name]['family'] not in families:
            continue
        sp = dict(sensitivity[name], hi_limit=P['hi_limit'])
        for s, rel in sp['base'].items():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            if not (dst / rel).exists():
                shutil.copy2(src / rel, dst / rel)
        if (src / 'runs' / name).exists() and not (dst / 'runs' / name).exists():
            shutil.copytree(src / 'runs' / name, dst / 'runs' / name)          # same seeds, same offset: identical runs
        specs.append(sp)
    if not specs:
        sys.exit('nothing new to prepare')
    fleet_scan.write_series(dst, specs)


def fresh_study(dst):
    """series.json is hashed into the file-integrity record of the study (`FREEZE.json`), so a study is never
    extended: later batches get a new name."""
    if (dst / 'series.json').exists():
        sys.exit('%s already exists; put further series into a new study (e.g. %s2)' % (dst.name, dst.name))


def taken(prefix):
    """Series names already defined in the studies <prefix>, <prefix>2, ..."""
    out = set()
    for p in STUDY_ROOT.glob(prefix + '*/series.json'):
        out |= {sp['name'] for sp in json.loads(p.read_text(encoding='utf8'))}
    return out


def prepare_candidates(study):
    import csv
    P = design('slow_handling.json')['part_b']
    sensitivity = json.loads((STUDY_ROOT / 'sensitivity' / 'series.json').read_text(encoding='utf8'))
    fresh_study(STUDY_ROOT / study)
    done = taken('candidates_')
    kf = {}
    for p in [STUDY_ROOT / 'results' / 'sensitivity_fleets.csv'] + sorted((STUDY_ROOT / 'results').glob('unresolved_scan*_fleets.csv')):
        if p.exists():
            for r in csv.DictReader(open(p, encoding='utf-8-sig')):
                if r['K_final'] not in ('', 'None'):
                    kf[r['series']] = int(float(r['K_final']))
    items = []
    for fac in P['factors']:
        gen = next(sp['gen'] for sp in sensitivity if sp['name'].startswith(fac + '_'))
        for cell in P['cells']:
            k0 = kf.get('%s_%s_T550' % (fac, cell))
            if k0 is None:
                print('skip %s %s: no count for 550 t yet (run unresolved_scan first)' % (fac, cell))
                continue
            for fam in P['families'][cell.split('_')[0]]:
                if fam.endswith('xN'):                       # mass-matched mix, rule from `slow_handling.json`
                    fam = '%s%d' % (fam[:-1], min(k0 - 1, math.ceil(k0 * P['h'][cell] - 1e-9)))
                name = 'cand_%s_%s_%s' % (fac, cell, fam)
                if name not in done:
                    items.append((name, cell, fam, gen, k0))
    if not items:
        sys.exit('nothing new to prepare')
    X.build(STUDY_ROOT / study, items, fleet_scan.SEEDS, P['seed_offset'])
    specs = json.loads((STUDY_ROOT / study / 'series.json').read_text(encoding='utf8'))
    fleet_scan.write_series(STUDY_ROOT / study, [dict(sp, hi_limit=40) for sp in specs])
    print('base files identical to sensitivity:', same_as(study, 'sensitivity'))


def status(study):
    p = STUDY_ROOT / study / 'progress.json'
    print(p.read_text(encoding='utf8') if p.exists() else 'no progress.json yet')


if __name__ == '__main__':
    cmd, study = sys.argv[1], sys.argv[2]
    if cmd == 'run':
        X.run(STUDY_ROOT / study, int(sys.argv[3]) if len(sys.argv) > 3 else 8)
    elif cmd == 'status':
        status(study)
    else:
        f = {'prepare-fresh-days': prepare_fresh_days, 'prepare-extended-mixes': prepare_extended_mixes, 'prepare-unresolved': prepare_unresolved, 'prepare-candidates': prepare_candidates}[cmd]
        f(study, tuple(sys.argv[3:])) if cmd == 'prepare-unresolved' else f(study)
