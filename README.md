# Shipyard transporter capacity choice at equal service: code and data

This repository accompanies the manuscript "Shipyard transporter capacity choice for single or coupled carriage of
heavy hull blocks at equal service". It contains only the code and data that produce or support the numbers,
tables and figures of the paper.

The digitised road network of the main shipyard, the instances generated on it and the individual schedules are not
released, because travel times reveal the facility layout; they are available to reviewers on request. Scripts that
need them are included so that every computation can be read, and are marked "main-yard instances" below. The second
case uses published data and can be rerun end to end.

## Environment

CPython 3.11 with numpy, scipy, openpyxl, psutil, matplotlib and OR-Tools 9.15 (analysis, pricing, lower bounds, the
exact solver for single-batch instances); PyPy 3.9 (7.3.15) for the scheduling runs (`fleet_scan.py`, `fleet_scan_studies.py`), which give identical results
under CPython, only more slowly. On Windows, PyPy mis-decodes non-ASCII command-line arguments and some pathlib calls on
non-ASCII paths: run the drivers by relative path from the repository root, from an ASCII directory. Scripts are run
from `fleet_sizing/code/` unless stated otherwise.

Search seeds are derived from the instance seed in `fleet_scan.py` and `fleet_scan_studies.py` (a fixed offset per study plus
1000 per repeated search); with the same instances, rerunning a study with the released code reproduces its schedules
exactly (only the recorded run times differ), as checked on stored runs of the second case.

## Study directories

Each study keeps its fleet series under `fleet_sizing/<directory>/` and its result tables under `fleet_sizing/results/`,
with file names that start with the directory name. The directory names are also the command-line arguments.

| Directory | Study |
| --- | --- |
| `main` | Main study: 36 conditions x 11 fleet families, 30 daily instances each |
| `overweight_only` | Overweight-only coupling runs of the two mixes |
| `delay_cap` | Delay-cap study: per-block delay caps from none to 30 min |
| `second_case` | Second case on the published data of Liu et al. (2022) |
| `tier_speeds`, `tier_speeds_jiang` | Tier-specific speeds |
| `sensitivity` | One-factor sensitivity and decision boundaries |
| `heavy_share` | Heavy-block share |
| `exact` | Exact comparison on single-batch instances |
| `robust` | Robust sizing under handling variability |

## Names in the data

A condition is named `<masses>_<handling>_<due dates>`, for example `jiang_short_baseline`. Masses: `jiang`,
`lightskew`, `uniform`, `extraheavy`, `rohcha` (Roh-Cha sample), `liu` (Liu week); handling: `short`, `massdep`
(mass-dependent), `long` (long loading); due dates: `baseline`, `tight` (Table 2 of the paper).

A fleet series adds the fleet family to the condition: a capacity tier in t (`200` to `550`, written `T380` in some
studies), `MX1` or `MX2` (one or two heavy members with 270 t light members), or `L300_H425x2` (light tier 300 t,
heavy tier 425 t, two heavy members); the suffix `_rigid` marks overweight-only coupling. Study prefixes: `T120_`
(delay cap in min; `Tinf_` without a cap), `tierspeed_` (tier-specific speeds), `heavy0.20_` (heavy-block share 0.20).
In the second case, `yard2_k6_flex_ADD250` is the published fleet plus added 250 t transporters at workload scale
k = 6 with coupling allowed (`nocoup`: not allowed).

## Where each result comes from

| Paper item | Script | Data | Rerun without main-yard instances |
| --- | --- | --- | --- |
| Table 2 price curve, exponent interval, lack of fit | `price_curve.py` (reads Table S1 when the authors' working record is absent) | `results/S1_price_sources.csv` | Yes |
| Table 2 price ratio r (5.1-30) | `price_curve.py`, `make_supplementary.py` | `results/price_curve.json` | Yes |
| Supplementary Tables S1, S2 | `make_supplementary.py` | S1 is generated from the authors' working record and released as data; S2 from `results/price_curve.json` | S2: yes |
| Fleet counts K* (Table in Appendix C) | `fleet_scan.py run main` then `analyse_study.py main` | `results/main_fleets.csv` | Counts: main-yard instances. Table: from the CSV |
| Cheapest fleets, 6,480 settings; certain vs search-dependent (5,033) | `cost_decisions.py ../results/main_fleets.csv main` | `results/main_fleets.csv` | Yes |
| Coupled share of winners (90.8%, 57.5%, 1.2%, 26.1%; 29 of 36 conditions) | `decision_strength.py` | `main_fleets.csv`, `main_decisions.csv` | Yes |
| Synchronisation waiting and coupled service share (0.19%, 9.0%, ...) | `decision_strength.py` (`_mechanism`) | pricing schedules | Main-yard instances; stored in `claim_numbers.json` |
| After-shift work (1.9 h; 67 of 1,620) | `analyse_study.py`, `cost_decisions.py` | `main_fleets.csv` | Yes, from the CSV |
| Fig. 3 (winner map, coupling and cost) | `paper/figs/make_figures.py` | `main_fleets.csv`, `main_decisions.csv`, `bootstrap_decisions.csv`, `grading_decisions.csv`, `claim_numbers.json` | Yes |
| Greedy pipeline (561 of 1,620; 88/253/43 series); search levels (65-100%) | `greedy_level.py`, `analyse_study.py`, `report_main.py` | `main_search_levels.csv` | Level counts: main-yard instances. Agreement: from the CSV |
| Load rule (within one transporter; up to five under) | `report_main.py` | `main_load_rule.csv` | K_rho: main-yard instances. Errors: from the CSV |
| Fig. 5 (search levels, load rule) | `paper/figs/make_figures.py` | `main_search_levels.csv`, `main_decisions.csv`, `main_load_rule.csv` | Yes |
| Day resampling and main-claim support under resampling (1,350 of 1,620; 89.1%) | `decision_strength.py` | `main_runs_compact.csv`, `main_fleets.csv`, `main/series.json` | Yes |
| Grading of search-dependent decisions (3,513 / 298 / 1,222) | `decision_strength.py` | `main_runs_compact.csv`, `main_decisions.csv` | Yes |
| Handling variability (9.5 points; 354 of 384; ranks 19 of 36) | `schedule_replay.py main`; ranks in `decision_strength.py` | `main_replay.json` | Replay: main-yard instances. Ranks: from the JSON |
| Pooling across families (0 of 384; 30 of 4,860) | `family_pooling.py` | `family_pooling.csv` | Main-yard instances |
| Lower bounds at four transporters (117 vs 146) | `bounds_simple.py`, `bounds_colgen.py`, `bounds_cpsat.py` | `bounds_final.csv`, `bounds_L4_summary.csv` | Main-yard instances |
| Second yard (Table 3, Appendix table; 425 t, 2.2-7.5%) | `fleet_scan_studies.py prepare-second-case second_case`, `fleet_scan_studies.py run second_case`, `analyse_study.py second_case`, `schedule_replay.py second_case`, `report_second_case.py` | `pone.0265047.s001.xlsx`, `paper/runs/second_case_scan/*`, `data/liu2022_distance_closure.csv` | Yes, end to end |
| Delay-cap axis and Fig. 4 (Section 5.2: smallest count five at every cap; eight series one transporter fewer without a cap; cheapest fleet and its coupled share) | `fleet_scan_studies.py run delay_cap`, `report_delay_cap.py`, `report_delay_cap.py grid`, `report_delay_cap.py late`, `paper/figs/make_figures.py` | `delay_cap_fleets.csv`, `delay_cap_grid.csv`, `delay_cap_late_blocks.csv`, `main_fleets.csv` | Counts and late blocks: main-yard instances. Pricing and figure: from the CSVs |
| Tier-specific speeds in six conditions (Section 5.4) | `report_tier_speeds.py` | `main_fleets.csv`, `tier_speeds_fleets.csv`, `tier_speeds_jiang_fleets.csv`, `main_decisions.csv` | Counts: main-yard instances. Comparison: from the CSVs |
| Liu mixes of 425 and 300 t (Section 5.1) | `compare_liu_mixes.py` | `main_fleets.csv`, `delay_cap_fleets.csv`, `tier_speeds_fleets.csv`; output `liu_mix_compare.json` | Counts: main-yard instances. Comparison: from the CSVs |
| Heavy-block share threshold (Section 5.1) | `fleet_scan_studies.py prepare-heavy-share`/`run heavy_share`, `report_studies.py heavy_share` | `heavy_share_fleets.csv`, `heavy_share_decisions.csv`, `heavy_share_thresholds.csv` | Counts: main-yard layout. Tables given |
| Overweight-only coupling and PoR (Appendix C) | `fleet_scan_studies.py prepare-overweight-only`/`run overweight_only`, `report_studies.py overweight_only` | `overweight_only_fleets.csv`, `overweight_only_por.csv`, `main_fleets.csv` | Counts: main-yard instances. Tables given |
| Exact comparison on single-batch instances; robust sizing | `exact_slices.py`, `exact_model.py`, `exact_run.py`, `exact_analyse.py`; `robust_sizing.py` | results added when those studies finish | Main-yard instances |

`analyse_study.py` also produces the fleet table of the sensitivity study; its result tables are added when the study
finishes.

## Licences

Code: MIT (`LICENSE`). Tables and supplementary data: CC BY 4.0 (`LICENSE-DATA.md`); third-party data
keep their original licences.

## Differences from the working copy

In the released copy, the name of the main shipyard is replaced by a neutral term, and comments that cite internal working documents are shortened, in: `paper/code/common/core.py`, `paper/code/common/params.py`, `paper/code/search/config.json`, `paper/code/instances/liu_days.py`, `paper/code/instances/instance_setup.py`, `fleet_sizing/code/fleet_scan.py`, `fleet_sizing/code/price_curve.py`, `fleet_sizing/solver_reference/common/core.py`, `fleet_sizing/solver_reference/search/alns.py`, `fleet_sizing/solver_reference/search/baselines.py`, `fleet_sizing/solver_reference/search/config.json`, `fleet_sizing/solver/common/core.py`, `fleet_sizing/solver/search/alns.py`, `fleet_sizing/solver/search/baselines.py`, `fleet_sizing/solver/search/config.json`. Comments, docstrings and report labels are in English in every released file. In `fleet_scan.py`, the file-integrity check of a study no longer includes an unreleased working document. The code is otherwise identical to the version used for the results.
