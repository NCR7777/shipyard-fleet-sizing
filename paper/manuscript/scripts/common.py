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
