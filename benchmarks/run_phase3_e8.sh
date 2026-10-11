#!/bin/sh
# E8: baseline heuristic vs CP-SAT on the SAME specs: the 23 saved (reconstructed) ones and the 14 held-out ones.
# CP-SAT configurations (grid 0.1, 1 worker, seed 1, 20 s):  A = base model, feasibility objective (the shipped default)
#                                                           B = A + core_first
#                                                           C = B + objective min_bbox_area (compactness)
# Sequential. The held-out specs were generated before configurations were compared and are only used to confirm.
cd "$(dirname "$0")/.."
for sp in specs specs_holdout; do
  tag=$([ $sp = specs ] && echo saved || echo holdout)
  ./.venv/bin/python benchmarks/experiment.py "e8_${tag}_heuristic" --specs $sp --method heuristic --note "E8 $tag: baseline heuristic"
  ./.venv/bin/python benchmarks/experiment.py "e8_${tag}_A_base" --specs $sp --note "E8 $tag: A base"
  ./.venv/bin/python benchmarks/experiment.py "e8_${tag}_B_core_first" --specs $sp --set model_options=core_first --note "E8 $tag: B core_first"
  ./.venv/bin/python benchmarks/experiment.py "e8_${tag}_C_core_first_bbox_area" --specs $sp --set model_options=core_first --set objective=min_bbox_area --note "E8 $tag: C core_first + min_bbox_area"
done
