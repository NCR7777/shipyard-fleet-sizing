# Exact comparison on single-batch instances: summary

## Consistency checks (must all be 0)

{"alns_below_bound": 0, "arm_below_klb": 0, "monotonicity": 0, "replay": 0}

## Exact counts

56 of 70 series have a proven K*; 7 have an interval; 7 have no passing count up to the ceiling.

- final: same 54, +1 2, +2 or more 0, below 0, no count 0
- single: same 52, +1 4, +2 or more 0, below 0, no count 0
- cp0: same 45, +1 11, +2 or more 0, below 0, no count 0
- cp100: same 50, +1 6, +2 or more 0, below 0, no count 0
- cp300: same 51, +1 5, +2 or more 0, below 0, no count 0
- greedy: same 6, +1 35, +2 or more 14, below 0, no count 1

## Primary endpoint

Tier A. {"certified": 360, "uncertified": 0, "agree": 360, "rate": 1.0, "near_tie_disagreements": 0, "separated": 0, "agree_separated": 0, "near": 360, "agree_near": 360, "final": 1.0, "single": 1.0, "cp0": 0.625, "cp100": 1.0, "cp300": 1.0, "greedy": 0.75}

- ALNS single run (j = 0) on 1147 proven (instance, K): optimal 1079; excess mean 0.059, max 1; over the cap 0
- ALNS best of the available runs on 1147 proven (instance, K): optimal 1103; excess mean 0.038, max 1; over the cap 0
