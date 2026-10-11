#!/bin/sh
# E2: E1 is one run per option, i.e. dominated by search luck. E2 repeats the interesting configurations over 5 solver seeds
# (1-5) on the 4 UNKNOWN cases + guard cases 17,18,19. Two streams run CONCURRENTLY (2 CPUs, 1 worker each); both streams are always
# busy, so every configuration sees the same load. Timings are therefore somewhat slower than E1's sequential runs.
cd "$(dirname "$0")/.."
CASES=15,20,21,22,17,18,19
run() { ./.venv/bin/python benchmarks/experiment.py "e2_$1" --cases $CASES --seeds 1,2,3,4,5 ${2:+--set model_options=$2} --note "E2 five seeds: ${2:-base}"; }
( run base ""; run mirror_symmetry mirror_symmetry ) > /tmp/claude-0/e2_A.log 2>&1 &
( run cumulative_cuts cumulative_cuts; run linear_adjacency linear_adjacency ) > /tmp/claude-0/e2_B.log 2>&1 &
wait
