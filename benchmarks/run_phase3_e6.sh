#!/bin/sh
# E6: compactness objectives and the heuristic warm start. Cases the base model solves quickly (so the objective, not feasibility, is
# what is measured): 0,1,2,3,7,9,10,11,12,14,16. The heuristic's own layout is VALID only for 0, 3 and 7 (see heuristic_hint_valid).
# Same settings as the benchmark (grid 0.1, 1 worker, seed 1, 20 s) except for the objective / hint. Sequential.
cd "$(dirname "$0")/.."
CASES=0,1,2,3,7,9,10,11,12,14,16
for obj in feasibility min_bbox_perimeter min_bbox_area; do
  for hint in none heuristic_hint; do
    if [ $hint = none ]; then H=""; else H="--set model_options=heuristic_hint"; fi
    ./.venv/bin/python benchmarks/experiment.py "e6_${obj}_${hint}" --cases $CASES --set objective=$obj $H --note "E6 objective=$obj hint=$hint"
  done
done
