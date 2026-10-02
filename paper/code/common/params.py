"""Baseline and scenario parameters.

Each item states its source. Scenario parameters without a literature source are marked as assumptions and are not
described as taken from the literature.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.normpath(os.path.join(HERE, '..', '..'))
MAP_PATH = os.path.join(PAPER, 'instances', 'map', 'rs-tif-09.map.json')
MAP_SHA256 = '9b6ce0a076ce250ead26cc7d80d82ef194164d196150068b1da52b7fe9d52c2a'   # SHA-256 of the map file
JIANG_TASKS = os.path.join(PAPER, 'params', 'jiang2021_tasks.csv')

# ---- Vehicles ----
V_EMPTY = 12.0 / 3.6      # m/s, empty 12 km/h (Dafang DCY270 specification)
# Speed scenarios: 'base' = maximum values of the specification; 'x0.5' = both halved; 'V-liu' = model parameters of
# Liu 2022 §4.1.1 ("under load is 30 meter/min…under no load is 50 meter/min", checked against the paper).
# Values are (empty, loaded) m/s.
SPEEDS = {'base': (12.0 / 3.6, 6.0 / 3.6), 'x0.5': (6.0 / 3.6, 3.0 / 3.6), 'V-liu': (50.0 / 60, 30.0 / 60)}
# Equal speeds for all tiers is an assumption: Dafang DCY380 runs 10/5 km/h and DCY500 12/5 km/h.
V_LOADED = 6.0 / 3.6      # m/s, loaded 6 km/h (Dafang DCY270)
PLAT_LEN = 16.25          # m, DCY270 platform length; lower bound of the parked footprint length
# Capacity tiers (t):
#   200/250/270/325/380/425: Jiang 2021 Table 5; 300/500/550: Roh & Cha 2011 Table 1; 250 also Liu 2022 Table 4.
#   No source has a 450 t transporter (Jiang's 450 is a block mass), so 450 t can only be an assumption.
CAP_TIERS = (200, 250, 270, 300, 325, 380, 425, 500, 550)
# Tiers used to generate the validation instance sets (toy / small / small_tight / tuning), kept for reproducibility:
VALID_TIERS = (200, 270, 300, 325, 380, 425, 450, 500, 550)
F_J21 = (200, 200, 200, 200, 250, 270, 325, 380, 380, 425)   # Jiang 2021 Table 5 (params/jiang2021_fleet.csv)

# ---- Workload and horizon ----
N_TASKS = 97              # Roh & Cha 2011, PDF p.18 (printed p.3246): "97 blocks from 8:00 a.m. to midnight"
HORIZON_H = 16.0
N_BATCHES = 8             # assumption: the source releases blocks one by one every half hour, not in batches
BATCH_LEN_S = 2 * 3600    # 16 h / 8 batches
# Required delivery = release + U(a, b) min. The 10 rows of Roh & Cha 2011 Table 2 (PDF p.20) give
# "available -> planned completion" intervals of 150–210 min (60% at 150), so all of U(120,150) lies below the
# sample minimum. Baseline: the empirical distribution of Table 2; tight due dates U(120,150) as a second level
# (assumption). A dict value is sampled as an empirical distribution, an (a, b) value uniformly.
DUE_EMPIRICAL = {150: 0.6, 180: 0.2, 210: 0.2}
DUE_TIGHT = (120, 150)
DUE_MIN = DUE_EMPIRICAL
VALID_DUE_MIN = (120, 150)  # as generated for the validation sets (tighter than the source; solver tests only)

# ---- Block dimensions ----
BLOCK_W = (5, 15)         # m, public instances of Kweon 2026
BLOCK_L = (10, 30)        # m, same source; length ≥ max(width, 10)

# ---- Scenario parameters (no literature source; covered by sensitivity analysis) ----
DELTA_MIN = 10            # coupling alignment time δ, baseline 10 min, sensitivity 0 / 20 min
DELTA_SENS = (0, 20)
CREW = 4                  # persons per vehicle, Park & Seo 2012 p.3 (4–5 persons); sensitivity 1 / 2 / 6 (assumption)
CREW_SENS = (1, 2, 6)
# Crew measure for the joint work of a team (core.py): default = CREW persons per vehicle × team size.
# Goldhofer brochure p.3: "usually requiring only one operator to control the transport combination" (this concerns
# modular trailers, not shipyard block transporters); hence the scenario "a team is staffed like one vehicle":
CREW_TEAM_ONE_UNIT = {1: CREW, 2: CREW, 3: CREW}
# Both crew measures are baseline scenarios: P-veh = None (CREW persons per vehicle × size) and
# P-team = CREW_TEAM_ONE_UNIT. Under P-team, empty travel and synchronisation wait still count CREW persons per
# vehicle, i.e. the extra persons are assumed to be released for other work during the joint work.
CREW_MODELS = {'P-veh': None, 'P-team': CREW_TEAM_ONE_UNIT}
MAX_TEAM = 3              # maximum team size (assumption); sensitivity 2
# Objective weight λ: one person-second of labour counts as λ seconds of tardiness (assumption); this value is also
# used by the validation instance sets.
LAMBDA_BASE = 0.1
# Pareto scan: logarithmic spacing; λ = 0 is lexicographic, tardiness first and labour second (core.LEX_EPS).
# The grid must contain the knee of the front on the tuning-seed instances.
LAMBDA_GRID = (0.0, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0)

# time_limit of the experiment runs: a safeguard only; runs stop at max_iter
FORMAL_TIME_LIMIT_S = 1800.0
# Task count for the Roh & Cha fleet with Roh–Cha masses: round(97 × 4 / 10) = 39, the same tasks per vehicle as Jiang
RC_N_TASKS = 39

MASS_SCEN = ('jiang', 'lightskew', 'uniform', 'extraheavy')     # the validation instance sets cycle through these 4; kept unchanged
MASS_SCEN_ALL = ('jiang', 'lightskew', 'uniform', 'extraheavy', 'rohcha')
MASS_SCEN_SCAN = ('jiang', 'lightskew', 'uniform', 'extraheavy', 'rohcha', 'liu')     # used by the earlier ten-instance scan
# `liu`: block masses of the 50 tasks in S1 Data of Liu, Yin & Khan 2022 (one real week of plans at Shanghai
# Waigaoqiao), sampled with replacement. One value per task (a block moved several times in the week counts each
# time); read from the xlsx by code/instances/liu_data.read_tasks and copied one by one.
LIU_S1_MASSES = (211, 286, 371, 385, 230, 230, 204, 392, 387, 290, 300, 218, 373, 230, 230, 345, 217, 268, 204, 392,
                 387, 359, 368, 274, 295, 237, 211, 286, 352, 399, 381, 345, 217, 268, 384, 390, 284, 306, 321, 338,
                 300, 218, 373, 206, 230, 230, 226, 395, 342, 286)
# `rohcha`: masses of the 10 blocks in Roh & Cha 2011 Table 2 (PDF p.20), sampled with replacement; paired with the
# Roh & Cha fleet. Only 10 rows, which the source calls "Selected" without describing the selection (a limitation).
ROH_CHA_MASSES = (275, 513, 465, 358, 281, 290, 487, 260, 489, 544)
ROH_CHA_FLEET = (300, 500, 500, 550)     # Roh & Cha 2011 Table 1
HANDLING = ('short', 'massdep', 'long')


def jiang_masses(which=('T20', 'T30', 'T40'), dedup=False):
    """Empirical distribution of the Jiang masses (`jiang`): block masses (t) of Jiang 2021 Tables 5, `A1` and `A2`.
    dedup=True (used in the experiments): a task with the same task number and mass in several instances counts once.
    dedup=False: the three sets pooled, 90 rows (as used to generate the validation instance sets; kept unchanged).
    The CSV column headings read here are Chinese: instance, task number and mass in t."""
    out, seen = [], set()
    with open(JIANG_TASKS, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row['实例'] in which:
                key = (row['任务号'], row['质量_t'])
                if dedup and key in seen:
                    continue
                seen.add(key)
                out.append(int(row['质量_t']))
    return out


def draw_mass(rng, scen, jiang_pool=None):
    """Draws one block mass (integer t) for a mass scenario.
    `jiang`: empirical distribution of Jiang 2021 (sampled with replacement);
    `lightskew`: 90% U(100,300), 10% U(300,500) (Park & Seo 2012 p.1 states only "100 to 300 tons, some blocks more than
        500 tons"; the shares and the 300–500 range are assumptions);
    `uniform`: U(100,500) (generated data of Kweon 2026);
    `extraheavy`: U(500,800) with probability 10%, otherwise as `lightskew` (tail share and range are assumptions);
    `rohcha`: the 10 masses of Roh & Cha 2011 Table 2, sampled with replacement;
    `liu`: the masses of the 50 tasks in S1 Data of Liu 2022, sampled with replacement."""
    if scen == 'jiang':
        return rng.choice(jiang_pool)
    if scen == 'lightskew':
        return rng.randint(100, 300) if rng.random() < 0.9 else rng.randint(300, 500)
    if scen == 'uniform':
        return rng.randint(100, 500)
    if scen == 'extraheavy':
        return rng.randint(500, 800) if rng.random() < 0.1 else draw_mass(rng, 'lightskew')
    if scen == 'rohcha':
        return rng.choice(ROH_CHA_MASSES)
    if scen == 'liu':
        return rng.choice(LIU_S1_MASSES)
    raise ValueError(scen)


def handling(rng, setting, mass, op):
    """Duration (s) of one load (op='load') or unload (op='unload').
    `short`: Liu 2022 PLOS ONE p.11, 10 min each;
    `massdep`: Kim & Joo 2012 IJPR p.10, U(10,20) + (0.05·m − 10) + 5 min; the source covers masses of 10–100 t, so using
        it for 100–800 t is an extrapolation (assumption); the source does not say whether this is load and unload
        together or each, and here it applies to each (assumption);
    `long`: Liu 2022 p.15, load U(30,60) min (an empirical statement in the discussion); unload takes the 10 min of the
        same paper's example (p.11); combining the two is an assumption. The working day of Roh & Cha implies at most
        about 24 min of handling per block, and under `long` that fleet cannot move 97 blocks in 16 h."""
    if setting == 'short':
        return 600.0
    if setting == 'massdep':
        return 60.0 * (rng.uniform(10, 20) + (0.05 * mass - 10) + 5)
    if setting == 'long':
        return 60.0 * rng.uniform(30, 60) if op == 'load' else 600.0
    raise ValueError(setting)
