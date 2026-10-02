# Service-constrained sizing and composition of shipyard block-transporter fleets: code and data

This repository accompanies the manuscript "Service-constrained sizing and composition of shipyard block-transporter
fleets with cooperative lifting". It contains the scheduling, sizing and pricing code, the result tables of every
study, the run-level results of all 214,210 scheduling runs (one row per run) and the transporter price sources.

The digitised road network of the main shipyard, the instances generated on it and the individual schedules are not
released, because travel times reveal the facility layout; they are available to reviewers on request. Scripts that
need them are included so that every computation can be read, and are marked "main-yard instances" below. The second
case uses published data and can be rerun end to end.

## Environment

CPython 3.11 with numpy, scipy, pandas, openpyxl, psutil, matplotlib and OR-Tools 9.15 (analysis, pricing, figures,
lower bounds, the exact solver for single-batch instances); PyPy 3.9 (7.3.15) for the scheduling runs (`fleet_scan.py`,
`fleet_scan_studies.py`), which give identical results under CPython, only more slowly. On Windows, PyPy mis-decodes non-ASCII
command-line arguments and some pathlib calls on non-ASCII paths: run the drivers by relative path from the repository
root, from an ASCII directory. Scripts are run from `fleet_sizing/code/` unless stated otherwise; the scripts in
`fleet_sizing/supplementary/` and `fleet_sizing/supplementary_outage/` are run from their own folder.

Search seeds are derived from the instance seed in `fleet_scan.py` and `fleet_scan_studies.py` (a fixed offset per study plus
1000 per repeated search); with the same instances, rerunning a study with the released code reproduces its schedules
exactly (only the recorded run times differ), as checked on stored runs of the second case.

## Studies

Each study has a directory name, which is also its command-line argument and the prefix of its result tables in
`fleet_sizing/results/`. The study directories themselves (instances and run files) are not released, except the
fleet series of the main study (`fleet_sizing/main/series.json`).

| Directory | Study | Section |
| --- | --- | --- |
| `main` | Main study: 36 operating conditions x 11 reference fleet types, 30 days each | 5.1, 5.2 |
| `delay_cap` | Lateness cap from none to 30 min, with extended light-heavy mixes | 5.3, 5.4 |
| `overweight_only` | Restricted coupling rule for the mixes | 5.4 |
| `heavy_share` | Share of heavy blocks | 5.3 |
| `sensitivity` | One-factor sensitivity | 5.4, 5.5 |
| `delta_axis`, `delta_axis_mix` | Alignment time from 0 to 40 min (six fleet types) | 5.4 |
| `unresolved_scan`, `candidates_speed`, `candidates_handling` | Slow speed and long handling: unresolved series scanned up to 40 transporters; 425 t, 500 t and light-heavy mixes added at slow speeds and at long handling | 5.5 |
| `extended_mixes` | Extended light-heavy mixes in 13 further conditions | 5.3 |
| `fresh_days` | 30 fresh days for the 42 contending fleets | 5.5 |
| `outage` | Service lost with one transporter out | 5.4 |
| `service90`, `service98` | On-time targets of 90% and 98% | 5.4 |
| `boundary_search` | Six more searches per day at one transporter below the count found | 5.5 |
| `robust` | Robust sizing under handling-time noise | 5.5 |
| `exact` | Exact benchmark on single-batch slices | 5.5 |
| `tier_speeds`, `tier_speeds_jiang` | Tier-specific speeds | 6 (limitations) |
| `second_case` | Second case on the published data of Liu et al. (2022) | 5.5 |

## Run tables

`fleet_sizing/results/runs_compact/<directory>.csv` has one row per scheduling run: study, series, condition, fleet
type, count K, day seed, repeat j, status, blocks on time, blocks beyond the lateness cap, largest lateness (s),
crew-vehicle, crew-team and after-shift hours, coupled blocks, iterations, run time (s), and the on-time and over-cap
counts after 0, 100 and 300 iterations. Together the tables hold 214,210 runs. A study whose run folders start with
copies of another study's runs (the fresh-target studies `service90`, `service98` and the scan `unresolved_scan`) lists only its new runs;
the copies are in the tables of `main` and `sensitivity`.

## Names in the data

A condition is named `<masses>_<handling>_<due dates>`, for example `jiang_short_baseline`. Masses: `jiang` (Jiang sample), `lightskew`
(light-skewed), `uniform` (uniform), `extraheavy` (heavy tail), `rohcha` (Roh-Cha sample), `liu` (Liu sample); handling: `short` (short),
`massdep` (mass-dependent), `long` (long loading); due dates: `baseline` (empirical), `tight` (tight).

A fleet series adds the fleet type to the condition: a capacity tier in t (`200` to `550`, written `T380` in some
studies), `MX1` or `MX2` (270 t units with one or two heavy units), or `L300_H425x2` (300 t units with two 425 t units);
the suffix `_rigid` marks the restricted coupling rule. Study prefixes: `T120_` (lateness cap in min; `Tinf_` without a
cap), `tierspeed_` (tier-specific speeds), `heavy0.20_` (heavy-block share 0.20), `exact_` (exact benchmark), `fresh_` (fresh days),
`extmix_` (extended mixes), `cand_` (candidates added at slow speed or long handling). One-factor levels are prefixed by the
factor: `delta2.5`, `hand1.5`, `speed0.5`, `speedliu` (speeds reported by Liu et al., 2022), `team2`, `turn30` and so on.
In the second case, `yard2_k6_flex_ADD250` is the published fleet plus added 250 t transporters at workload scale k = 6
with coupling allowed (`nocoup`: not allowed).

The supplementary studies read their fleets, starting counts and seeds from design files (`fleet_sizing/supplementary/design/`,
`fleet_sizing/supplementary_outage/design/`). In the slow-speed and long-handling study, a mix of 300 t units with heavy units has
N = min(K - 1, ceil(K h)) heavy units, where K is the count of the 550 t (or 500 t) fleet in the same condition and h
the heavy blocks' share of handling time.

## Where each result comes from

| Paper item | Script | Data | Rerun without main-yard instances |
| --- | --- | --- | --- |
| Table 3: price curves, exponent, lack of fit; price ratio r | `price_curve.py` (reads the price-source table when the authors' working record is absent), `make_supplementary.py` | `results/S1_price_sources.csv`, `results/S2_price_ratio.csv`, `results/price_curve.json` | Yes |
| Fig. 3: transporters needed by tier | `fleet_scan.py run main`, `analyse_study.py main`; figure `paper/manuscript/scripts/fig3_tradeoff.py` | `results/main_fleets.csv` | Counts: main-yard instances. Figure: yes |
| Section 5.1, Table 5, Fig. 4: least-cost fleets, single-carry shares, margins | `cost_decisions.py ../results/main_fleets.csv main`, `decision_strength.py`; figure `paper/manuscript/scripts/fig4_winners.py` | `results/main_fleets.csv`, `results/main_decisions.csv`, `results/claim_numbers.json` | Yes |
| Section 5.2: vehicle-time decomposition (coupled occupancy, waiting, occupancy per block) | `supplementary/vehicle_time.py main 8 --with-r3` | `results/vehicle_time_summary.json`, `results/vehicle_time_series.csv`, `results/vehicle_time_pairs.csv` | Main-yard instances; tables given |
| Fig. 5: transporter-hours against coupled share; counts beyond the workload rule | `paper/manuscript/scripts/fig5_occupancy.py`; workload rule in `report_main.py` | `results/main_fleets.csv`, `results/main_load_rule.csv` | Figure: yes. Workload rule: main-yard instances |
| Fig. 6: winners as r varies far beyond its calibrated range | `paper/manuscript/scripts/fig6_breakeven.py` | `results/main_fleets.csv` | Yes |
| Fig. 7, heavy-block share regimes | `fleet_scan_studies.py run heavy_share`, `report_studies.py heavy_share`; figure `paper/manuscript/scripts/fig7_regimes.py` | `results/heavy_share_fleets.csv`, `results/heavy_share_decisions.csv`, `results/heavy_share_thresholds.csv` | Counts: main-yard instances. Tables and figure: yes |
| Liu sample with extended mixes (dense cost grid) | `compare_liu_mixes.py` | `results/main_fleets.csv`, `results/delay_cap_fleets.csv`, `results/tier_speeds_fleets.csv`; output `results/liu_mix_compare.json` | Yes |
| Extended mixes in 13 further conditions | `supplementary/confirm_run.py prepare-extended-mixes extended_mixes`, `run extended_mixes`, `analyse_study.py extended_mixes`, `supplementary/confirm_report.py extended-mixes` | `results/extended_mixes_fleets.csv`, `results/extended_mixes_decisions.csv`, `results/extended_mixes_report.json` | Counts: main-yard instances. Report: yes |
| Section 5.4: lateness cap, deferred blocks | `fleet_scan_studies.py run delay_cap`, `report_delay_cap.py`, `report_delay_cap.py grid`, `report_delay_cap.py late` | `results/delay_cap_fleets.csv`, `results/delay_cap_grid.csv`, `results/delay_cap_late_blocks.csv`, `results/delay_cap_axis.csv` | Counts and late blocks: main-yard instances. Pricing: yes |
| On-time targets of 90% and 98% | `supplementary_outage/service_level.py prepare/run/analyse/report` | `results/service90_fleets.csv`, `results/service98_fleets.csv`, `results/service98_precheck.csv`, `results/service_level_decisions.csv`, `results/service_level_report.json` | Main-yard instances; tables given |
| Restricted coupling rule | `fleet_scan_studies.py run overweight_only`, `report_studies.py overweight_only` | `results/overweight_only_fleets.csv`, `results/overweight_only_por.csv` | Counts: main-yard instances. Tables given |
| Alignment time | `fleet_scan_studies.py prepare-delta-axis delta_axis`, `prepare-delta-axis-mix delta_axis_mix`, `run`, `report_studies.py delta-axis` | `results/delta_axis_fleets.csv`, `results/delta_axis_mix_fleets.csv`, `results/delta_axis_levels.csv`, `results/delta_axis_summary.md` | Main-yard instances; tables given |
| One transporter out: N-1 sizing | `supplementary_outage/outage_sizing.py` | `results/outage_sizing_fleets.csv`, `results/outage_sizing_decisions.csv`, `results/outage_sizing_summary.json` | Main-yard instances (block masses); tables given |
| One transporter out: service lost | `supplementary_outage/outage_service.py prepare/run/analyse` | `results/outage_service_fleets.csv`, `results/outage_service_report.json`, `results/outage_service_report.md` | Main-yard instances; tables given |
| Section 5.5, Table 6: search depth, search dependence and grading | `greedy_level.py`, `analyse_study.py`, `report_main.py`, `decision_strength.py` | `results/main_search_levels.csv`, `results/grading_series.csv`, `results/grading_decisions.csv`, `results/main_runs_compact.csv` | Levels: main-yard instances. Agreement and grading: yes |
| Boundary re-search | `boundary_search.py select/run/analyse` | `results/boundary_search_series.csv`, `results/boundary_search_summary.json` | Main-yard instances; tables given |
| Exact benchmark | `exact_slices.py`, `exact_model.py`, `exact_run.py`, `exact_analyse.py` | `results/exact_kstar.csv`, `results/exact_decisions.csv`, `results/exact_gap.csv`, `results/exact_summary.md`, `results/exact_greedy.json` | Main-yard instances; tables given |
| Adversarial bound (one transporter fewer for coupling-reliant fleets) | `decision_strength.py bound` | `results/search_bound.json` | Yes |
| Day resampling | `decision_strength.py` | `results/bootstrap_series.csv`, `results/bootstrap_decisions.csv`, `results/main_runs_compact.csv` | Yes |
| Fresh days | `supplementary/confirm_run.py prepare-fresh-days fresh_days`, `run fresh_days`, `analyse_study.py fresh_days`, `supplementary/confirm_report.py fresh-days` | `results/fresh_days_fleets.csv`, `results/fresh_days_decisions.csv`, `results/fresh_days_report.json` | Counts: main-yard instances. Report: yes |
| Slow speed and long handling | `supplementary/structural_screen.py`, `screen_candidates.py`, `supplementary/confirm_run.py prepare-unresolved/prepare-candidates`, `candidates_handling.py`, `run`, `analyse_study.py`, `supplementary/confirm_report.py slow-handling` | `results/sensitivity_precheck.csv`, `results/slow_handling_screen_candidates.csv`, `results/unresolved_scan_fleets.csv`, `results/candidates_speed_fleets.csv`, `results/candidates_handling_fleets.csv`, `results/slow_handling_decisions.csv`, `results/slow_handling_report.json`; with the five one-factor types only: `results/slow_handling_report_five_types.json` | Screen and counts: main-yard instances. Report: yes |
| One-factor sensitivity | `fleet_scan_studies.py prepare-sensitivity sensitivity`, `run sensitivity`, `report_studies.py sensitivity` | `results/sensitivity_fleets.csv`, `results/sensitivity_levels.csv`, `results/sensitivity_boundaries.csv`, `results/sensitivity_boundary_summary.csv` | Counts: main-yard instances. Tables given |
| Handling-time noise, robust sizing (Fig. S1) | `schedule_replay.py main`, `robust_sizing.py`; figure `paper/manuscript/scripts/figS1_robust.py` | `results/main_replay.json`, `results/robust_series.csv`, `results/robust_decisions.csv`, `results/robust_summary.md` | Replay and sizing: main-yard instances. Figure: yes |
| Labour-specific schedules | `supplementary/labour_schedules.py` | `results/runs_compact/main.csv`, `results/main_fleets.csv`; output `results/labour_schedules_series.csv`, `results/labour_schedules_decisions.csv`, `results/labour_schedules_summary.json` | Yes |
| Tier-specific speeds | `report_tier_speeds.py` | `results/tier_speeds_fleets.csv`, `results/tier_speeds_jiang_fleets.csv`, `results/tier_speeds_decisions.csv` | Counts: main-yard instances. Comparison: yes |
| Second case (Table 7) | `fleet_scan_studies.py prepare-second-case second_case`, `run second_case`, `analyse_study.py second_case`, `schedule_replay.py second_case`, `report_second_case.py` | `pone.0265047.s001.xlsx`, `paper/runs/second_case_scan/*`, `data/liu2022_distance_closure.csv` | Yes, end to end |
| Lower bound at four transporters (Section 6) | `bounds_simple.py`, `bounds_colgen.py`, `bounds_cpsat.py` | `results/bounds_final.csv`, `results/bounds_L4_summary.csv` | Main-yard instances |
| Run tables | `export_runs.py` | `results/runs_compact/*.csv` | Main-yard run files |

Not yet in this repository: the fluid-model cost ratios of Sections 5.2 and 5.3 and the switch statistics of the
lower envelope in r (Section 5.2).

## Licences

Code: MIT (`LICENSE`). Tables, design files and price data: CC BY 4.0 (`LICENSE-DATA.md`); third-party data keep their
original licences.

## Differences from the working copy

In the released copy, the name of the main shipyard is replaced by a neutral term, and comments that cite internal working documents are shortened, in: `paper/code/common/core.py`, `paper/code/common/params.py`, `paper/code/search/config.json`, `paper/code/instances/liu_days.py`, `paper/code/instances/instance_setup.py`, `paper/manuscript/scripts/style.py`, `fleet_sizing/code/fleet_scan.py`, `fleet_sizing/code/price_curve.py`, `fleet_sizing/code/boundary_search.py`, `fleet_sizing/solver_reference/common/core.py`, `fleet_sizing/solver_reference/search/alns.py`, `fleet_sizing/solver_reference/search/baselines.py`, `fleet_sizing/solver_reference/search/config.json`, `fleet_sizing/solver/common/core.py`, `fleet_sizing/solver/search/alns.py`, `fleet_sizing/solver/search/baselines.py`, `fleet_sizing/solver/search/config.json`, `fleet_sizing/supplementary/confirm_run.py`, `fleet_sizing/supplementary_outage/outage_service_common.py`. Comments, docstrings and report labels are in English in every released file. In `fleet_scan.py`, the file-integrity check of a study no longer includes an unreleased working document. The supplementary drivers read their design files directly, without a checksum list, and the design files are released without the prose fields that the code never reads. The figure scripts create their output folder. Where names are renamed, a few lines that parsed the old names by width, and the keys of the outage report, are adapted. Report files that need main-yard runs to be rewritten (outage, on-time targets, robust sizing, vehicle-time summary) carry the labels of the released code; their numbers are unchanged, and the other supplementary reports are rewritten by the released code. The code is otherwise identical to the version used for the results.
