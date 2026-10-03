import sys, json, math
from pathlib import Path
import pandas as pd, numpy as np
BASE = Path(__file__).resolve().parents[3] / 'fleet_sizing'      # local project (was the unzipped data package)
RES = BASE/'results'
sys.path.insert(0, str(BASE/'code'))
import cost_decisions as RC
FAMS = ['200','250','270','300','325','380','425','500','550','MX1','MX2']
def fleets(fn='main_fleets.csv'):
    return pd.read_csv(RES/fn)

# Display labels. Keys are the condition and fleet codes used in the result files.
PROFILE = {'jiang': 'Jiang sample', 'lightskew': 'Light-skewed', 'uniform': 'Uniform', 'extraheavy': 'Heavy-tail profile',
           'rohcha': 'Roh–Cha sample', 'liu': 'Liu sample'}
RANGE = {'jiang': '38–450 t', 'lightskew': '100–500 t', 'uniform': '100–500 t', 'extraheavy': 'to 800 t', 'rohcha': '260–544 t', 'liu': '204–399 t'}
HANDLING = {'short': 'Short handling', 'massdep': 'Mass-dependent handling', 'long': 'Long loading'}
DUE = {'baseline': 'empirical', 'tight': 'tight'}
FLEET = {'MX1': '270 t + 1 heavy unit', 'MX2': '270 t + 2 heavy units'}
PROFILES = list(PROFILE)
COVER = {'jiang': 500, 'lightskew': 500, 'uniform': 500, 'extraheavy': None, 'rohcha': 550, 'liu': 425}   # smallest tier that carries every block


def split(cell):
    """Condition key -> (block-mass profile, handling regime, due-date regime)."""
    return tuple(cell.split('_'))


def fleet_label(fam):
    return FLEET.get(fam, '%s t' % fam)
