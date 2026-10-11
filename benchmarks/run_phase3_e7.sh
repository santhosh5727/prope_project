#!/bin/sh
# E7 determinism (this machine only). D1: base model, cases that finish well inside the limit. D2: an optimising objective that always
# runs into the time limit (outcome then depends on how much search fits in the wall-clock budget). D3: same case as D1 with a
# 3x longer limit (a limit that is not reached must not change the layout). D4: core_first on the case it proves infeasible.
cd "$(dirname "$0")/.."
./.venv/bin/python benchmarks/determinism.py e7_d1_base --cases 0,9,14,18 --n 5
./.venv/bin/python benchmarks/determinism.py e7_d2_bbox_area_5s --cases 9,11 --n 5 --set objective=min_bbox_area --set time_limit_s=5
./.venv/bin/python benchmarks/determinism.py e7_d3_base_60s --cases 0,9,14 --n 2 --set time_limit_s=60
./.venv/bin/python benchmarks/determinism.py e7_d4_core_first --cases 15 --n 3 --set model_options=core_first
