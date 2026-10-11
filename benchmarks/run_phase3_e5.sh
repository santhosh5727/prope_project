#!/bin/sh
# E5: are the two cases that never solved (21, 22) solvable with more time / workers? Diagnostic, different settings from the benchmark.
cd "$(dirname "$0")/.."
./.venv/bin/python benchmarks/experiment.py e5_long_1worker --cases 21,22 --set time_limit_s=120 --note "E5 diagnostic: 120 s, 1 worker, seed 1, base model"
./.venv/bin/python benchmarks/experiment.py e5_long_2workers --cases 21,22 --set time_limit_s=120 --set num_workers=2 --note "E5 diagnostic: 120 s, 2 workers (all CPUs), seed 1, base model"
