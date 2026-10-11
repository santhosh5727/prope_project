#!/bin/sh
# E1: effect of each model option ALONE (plus the base model) on the 4 UNKNOWN cases (15,20,21,22) and 5 guard cases that the
# base model solved in 5-12 s (3,13,17,18,19). Same settings as the recorded benchmark: grid 0.1, feasibility, 1 worker, seed 1, 20 s.
# Sequential on purpose (2 CPUs; concurrent runs would distort the timings). Output: benchmarks/runs/e1_*.json (never overwritten).
cd "$(dirname "$0")/.."
CASES=15,20,21,22,3,13,17,18,19
for opt in base tight_domains linear_adjacency cumulative_cuts mirror_symmetry twin_symmetry heuristic_hint; do
  if [ "$opt" = base ]; then SET=""; else SET="--set model_options=$opt"; fi
  echo "=== $opt"
  ./.venv/bin/python benchmarks/experiment.py "e1_$opt" --cases $CASES $SET --note "E1 single option: $opt"
done
