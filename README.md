# Single-vehicle capacity versus cooperative transport in shipyard block-transporter fleets: code and data

This repository accompanies the manuscript "Single-vehicle capacity versus cooperative transport in the
service-constrained sizing of shipyard block-transporter fleets". It contains the scheduling, sizing and pricing code, the result tables of every
study, the run-level results of all 214,210 scheduling runs (one row per run) and the transporter price sources.

The digitised road network of the main shipyard and the individual schedules are not released, nor are the instances
generated on it apart from their block masses, because travel times reveal the facility layout; they are available to
reviewers on request. The block masses of the main study and of the heavy-block share study are in
`fleet_sizing/results/runs_compact/tasks_main.csv` and `tasks_heavy_share.csv` (condition, day, block, mass). Scripts that need the
rest of the instances are included so that every computation can be read, and are marked "main-yard instances" below.
The second case uses published data and can be rerun end to end.

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
| `outage` | Service after reducing the capacity composition and reassigning starts | 5.4 |
| `service90`, `service98` | On-time targets of 90% and 98% | 5.4 |
| `boundary_search` | Six more searches per day at one transporter below the count found | 5.5 |
| `robust` | Robust sizing under handling-time noise | 5.5 |
| `exact` | Exact benchmark on single-batch slices | 5.5 |
| `tier_speeds`, `tier_speeds_jiang` | Tier-specific speeds | 5.6, 6 |
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
| Table 3 and the price tables of the Supplementary Material: price curves, exponent, lack of fit; capital-to-labour ratio (theta in the paper, `r` in the code and tables) | `price_curve.py` (reads the price-source table when the authors' working record is absent), `make_supplementary.py` | `results/price_sources.csv`, `results/price_ratio.csv`, `results/price_curve.json` | Yes |
| Fig. 4: transporters needed by tier | `fleet_scan.py run main`, `analyse_study.py main`; figure `paper/manuscript/scripts/fig3_tradeoff.py` | `results/main_fleets.csv` | Counts: main-yard instances. Figure: yes |
| Section 5.1, Table 5, Fig. 5: least-cost fleets, single-carry shares, margins | `cost_decisions.py ../results/main_fleets.csv main`, `decision_strength.py`; figure `paper/manuscript/scripts/fig4_winners.py` | `results/main_fleets.csv`, `results/main_decisions.csv`, `results/claim_numbers.json` | Yes |
| Section 5.2: vehicle-time decomposition (coupled occupancy, waiting, occupancy per block) | `supplementary/vehicle_time.py main 8`; `claim_checks.py` for the reported main-study subset | `results/vehicle_time_summary.json`, `results/vehicle_time_series.csv`, `results/vehicle_time_pairs.csv`, `results/vehicle_time_main_summary.json`, `results/vehicle_time_main_pairs.csv` | Main-yard instances; tables given |
| Fig. 6: transporter-hours against coupled share; counts beyond the workload rule | `paper/manuscript/scripts/fig5_occupancy.py`; workload rule in `report_main.py` | `results/main_fleets.csv`, `results/main_load_rule.csv` | Figure: yes. Workload rule: main-yard instances |
| Fig. 6(d): winners as theta varies beyond the calibrated range | `fluid_check.py`; `paper/manuscript/scripts/fig5_occupancy.py` | `results/main_fleets.csv`, `results/fluid_check.json` | Yes |
| Sections 3.3, 5.2 and 5.3: kappa, coupling budget, fluid and simulated cost ratios (with the test without the price factor), decisions priced on the workload rule, switch points of the lower envelope in theta, 300 t against 550 t as the heavy-block share grows | `fluid_check.py`, `fluid_verify.py` | `results/main_fleets.csv`, `results/main_load_rule.csv`, `results/heavy_share_fleets.csv`, `results/runs_compact/tasks_main.csv`, `results/runs_compact/tasks_heavy_share.csv`; output `results/fluid_check.json`, `results/fluid_pairs_main.csv`, `results/fluid_pairs_heavy_share.csv`, `results/fluid_verify.json` | Yes |
| Fig. 7: heavy-block share regimes | `fleet_scan_studies.py run heavy_share`, `report_studies.py heavy_share`; figure `paper/manuscript/scripts/fig6_regimes.py` | `results/heavy_share_fleets.csv`, `results/heavy_share_decisions.csv`, `results/heavy_share_thresholds.csv` | Counts: main-yard instances. Tables and figure: yes |
| Liu sample with extended mixes (dense cost grid) | `compare_liu_mixes.py` | `results/main_fleets.csv`, `results/delay_cap_fleets.csv`, `results/tier_speeds_fleets.csv`; output `results/liu_mix_compare.json` | Yes |
| Extended mixes in 13 further conditions | `supplementary/confirm_run.py prepare-extended-mixes extended_mixes`, `run extended_mixes`, `analyse_study.py extended_mixes`, `supplementary/confirm_report.py extended-mixes` | `results/extended_mixes_fleets.csv`, `results/extended_mixes_decisions.csv`, `results/extended_mixes_report.json` | Counts: main-yard instances. Report: yes |
| Section 5.4 and Fig. 8: lateness cap, deferred blocks | `fleet_scan_studies.py run delay_cap`, `report_delay_cap.py`, `report_delay_cap.py grid`, `report_delay_cap.py late` | `results/delay_cap_fleets.csv`, `results/delay_cap_grid.csv`, `results/delay_cap_late_blocks.csv`, `results/delay_cap_axis.csv` | Counts and late blocks: main-yard instances. Pricing and figure `paper/manuscript/scripts/fig7_service.py`: yes |
| On-time targets of 90% and 98% | `supplementary_outage/service_level.py prepare/run/analyse/report` | `results/service90_fleets.csv`, `results/service98_fleets.csv`, `results/service98_precheck.csv`, `results/service_level_decisions.csv`, `results/service_level_report.json` | Main-yard instances; tables given |
| Restricted coupling rule | `fleet_scan_studies.py run overweight_only`, `report_studies.py overweight_only` | `results/overweight_only_fleets.csv`, `results/overweight_only_por.csv` | Counts: main-yard instances. Tables given |
| Alignment time | `fleet_scan_studies.py prepare-delta-axis delta_axis`, `prepare-delta-axis-mix delta_axis_mix`, `run`, `report_studies.py delta-axis` | `results/delta_axis_fleets.csv`, `results/delta_axis_mix_fleets.csv`, `results/delta_axis_levels.csv`, `results/delta_axis_summary.md` | Main-yard instances; tables given |
| Redundancy estimate from reduced capacity compositions | `supplementary_outage/outage_sizing.py` | `results/outage_sizing_fleets.csv`, `results/outage_sizing_decisions.csv`, `results/outage_sizing_summary.json` | Yes (run tables and block masses) |
| Service loss with reduced capacity composition | `supplementary_outage/outage_service.py prepare/run/analyse` | `results/outage_service_fleets.csv`, `results/outage_service_report.json`, `results/outage_service_report.md` | Main-yard instances; tables given |
| Section 5.5, Table 6: search depth, search dependence and grading | `greedy_level.py`, `analyse_study.py`, `claim_checks.py` (four labour measures), `report_main.py` (shift labour), `decision_strength.py` | `results/main_search_levels.csv`, `results/grading_series.csv`, `results/grading_decisions.csv`, `results/main_runs_compact.csv` | Levels: main-yard instances. Agreement and grading: yes |
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
| Second case (Table 7) | `fleet_scan_studies.py prepare-second-case second_case`, `run second_case`, `analyse_study.py second_case`, `schedule_replay.py second_case`, `report_second_case.py` | `pone.0265047.s001.xlsx`, `data/second_case_extension_runs.csv`, `paper/runs/second_case_scan/scratch.json`, `data/liu2022_distance_closure.csv` | Yes, end to end |
| Lower bound at four transporters (Supplementary Section S7) | `bounds_simple.py`, `bounds_colgen.py`, `bounds_cpsat.py` | `results/bounds_final.csv`, `results/bounds_L4_summary.csv` | Main-yard instances |
| Run tables | `export_runs.py` | `results/runs_compact/*.csv` | Main-yard run files |

## Licences

Code: MIT (`LICENSE`). Tables, design files, block masses and price data: CC BY 4.0 (`LICENSE-DATA.md`); third-party
data keep their original licences.

## Recompute the decision checks

From the repository root:

```console
python fleet_sizing/code/decision_checks.py --results fleet_sizing/results --out decision_check_output
python fleet_sizing/code/fluid_check.py
python fleet_sizing/code/fluid_verify.py
```

The decision check reproduces 6,480 cost comparisons and quotation tie thresholds, 1,620 workload-rule decisions,
service at the original count on 30 fresh days for 42 fleets, and the distinct fleet counts of the lateness-cap study.
Its outputs are `cost_flip_thresholds.csv`, `workload_rule_decisions.csv`, `fresh_days_fixed_count.csv` and
`decision_checks.json`. Sections 5.1, 5.2 and 5.5 and Supplementary Sections S5 and S9 use these outputs.
The quotation sensitivity increases only the winner's fleet capital price, holding every rival and labour cost fixed.
It is a deterministic tie threshold, not an estimate of price uncertainty. A workload-rule count below the smallest
qualifying stored count is marked unsupported by the available schedule pool, without claiming physical infeasibility.

## Fleet aliases in the lateness-cap tables

The reference `MX1` and `MX2` labels mean 270 t units plus one or two covering heavy units. They duplicate the explicit
`L270_H500x1` / `L270_H500x2` types for the Jiang and uniform profiles, and `L270_H425x1` / `L270_H425x2` for the Liu profile.
The tables retain these rows so that existing analyses remain reproducible. Count distinct physical compositions when
reporting fleets: eight labels that need one fewer vehicle without a cap represent six fleet-condition pairs and five
fleet types. The candidate description has eleven reference types and ten further mix types.

## Figures and data access

The seven statistical and mechanism figure scripts in `paper/manuscript/scripts/` are
`fig1_mechanism.py` (Fig. 2), `fig3_tradeoff.py` (Fig. 4), `fig4_winners.py` (Fig. 5),
`fig5_occupancy.py` (Fig. 6), `fig6_regimes.py` (Fig. 7), `fig7_service.py` (Fig. 8) and
`figS1_robust.py` (Fig. S1). They read the released aggregate results. Set `OE_FIG_OUT` to select an
output folder; otherwise they write to `paper/manuscript/figures/`.

The current introduction (Fig. 1) and evaluation framework (Fig. 3) use the included SVG sources
`paper/latex/figs/fig_intro_b.svg` and `fig_framework.svg`. Export them with:

```console
python paper/figs/make_svg_figures.py
```

This command writes vector PDFs and 300 dpi PNG previews alongside the SVG inputs. Chrome or Chromium
must be installed; set `CHROME` to its executable path when it is not found automatically.
Together these sources reproduce all eight main figures and the supplementary figure.

The fluid-model scripts reproduce all 9,450 main comparisons, the one-sided 1.10 screen,
the 630 heavy-share comparisons and the lower envelope in theta. CSV field `r` and the internal
cost-code argument denote the paper's capital-to-labour ratio theta.

The main yard's layout, generated instances and schedules remain protected. Their block masses and aggregate fleet
and run results are included. Aggregate analyses can be recomputed without the layout; regenerating those schedules
requires reviewer access to protected inputs. The second case can be generated and run from its published source data.


## Recompute the reported table statistics

```console
python fleet_sizing/code/claim_checks.py
```

This standard-library script reproduces all 6,480 main procurement winners and all 3,600 slow-speed/long-handling
decisions, including the 540 without a qualifying fleet. It writes `table_checks.json`, `search_depth_summary.json`,
`search_depth_decisions.csv`, `slow_handling_max_coupling.csv`, `vehicle_time_main_summary.json` and
`vehicle_time_main_pairs.csv` under `fleet_sizing/results/`. Use `--out DIRECTORY` to write elsewhere.
The grid values stored to three decimals in the slow-handling and lateness-cap tables identify the full-precision
theta values in `main_decisions.csv`; the script uses those full-precision values for pricing.

Figure 6(b) and the vehicle-time statistics in Section 5.2 use the main study only: 266 fleet pairs outside the
heavy-tail profile with coupled-block shares above 1% and positive extra working time. The corresponding occupancy
and partner-waiting medians are 89.8% and 2.1%. Coupled occupancy includes repeated service and alignment; partner waiting excludes alignment. The existing `vehicle_time_series.csv`, `vehicle_time_pairs.csv` and
`vehicle_time_summary.json` also contain the additional mixes under the 120-minute cap; their 275-pair summary is
retained as a distinct aggregate scope. No underlying schedule or run record is discarded.

The search-depth row in Table 6 and Supplementary Table S1 reprices 6,480 decisions across four labour measures by
replacing only K. Working-time and overtime terms are retained from the final schedules in `main_fleets.csv`.
The single-carry category uses the coupled share of those final schedules. These comparisons measure the procurement
effect of count estimates; they do not reselect the schedules at each search depth. `report_main.py` separately
reports search-depth agreement under shift labour only (1,620 decisions).

## Capacity removal and the empirical fluid screen

The outage scripts analyse reduced capacity compositions using each fleet family's scanned, prefix start locations.
They do not delete an individual vehicle while preserving every survivor's original capacity and position.
The count estimate `max(K*_X, K*_(X-)) + 1` is stored in existing fields named `K_N1`.
It is a redundancy estimate, not an arbitrary-vehicle failure guarantee. Coupled shares in `outage_sizing_*`
describe normal-operation schedules with all purchased vehicles available; the 87.5% share has that scope.
The reduced-composition service probabilities use the same reassignment of starts. Existing result files retain
their numerical values and field names, including `worst unit out`; read those labels as capacity-class variants.

The 1.10 fluid screen uses occupancy calibrated from the covering fleet's schedules in the same simulated conditions.
Its 7,311 exclusions and one false exclusion among 9,450 comparisons describe this calibrated check, not independently
validated prediction on a new yard or input-only occupancy estimates. The two-member 2–18% coupling budget uses
shift labour and the fitted power law with exponent 0.84; the range across all five price curves is 1.9–21.8%.
