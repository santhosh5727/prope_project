#!/bin/sh
# E8b: E8's configuration C mixed two changes (core_first + min_bbox_area). D = min_bbox_area ALONE, same specs/settings, so the two can be separated.
cd "$(dirname "$0")/.."
for sp in specs specs_holdout; do
  tag=$([ $sp = specs ] && echo saved || echo holdout)
  ./.venv/bin/python benchmarks/experiment.py "e8_${tag}_D_bbox_area" --specs $sp --set objective=min_bbox_area --note "E8b $tag: D min_bbox_area without core_first"
done
