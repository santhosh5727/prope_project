# Pharma layout MVP — requirements → 2D layout → independent geometric validation

A small vertical slice. **All input data is synthetic.** This is a geometry-and-traceability
demonstrator. It is **not** a GMP/regulatory compliance tool and **not** production software.

## Run

The application, the baseline heuristic and the validator use only the Python standard library
(developed on Python 3.13). The CP-SAT generator additionally needs OR-Tools, installed **only** in a project venv:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements-cpsat.txt   # optional: ortools==9.15.6755

# web UI (http://127.0.0.1:8000/). With OR-Tools available the UI defaults to CP-SAT, otherwise to the baseline.
./.venv/bin/python -m pharma_layout serve --port 8000        # or: python3 -m pharma_layout serve   (baseline only)

# command line: generate + validate + write a standalone HTML report
./.venv/bin/python -m pharma_layout run examples/synthetic_osd_demo_30m.json --method cpsat --out report.html --json result.json
#   --method heuristic|cpsat overrides spec.generator.method (default: heuristic)

# tests (OR-Tools tests are skipped, not failed, when it is not installed)
./.venv/bin/python -m unittest discover -s tests -t . -v
python3 -m unittest discover -s tests -t . -v
```

CLI exit codes: **0** all checks pass · **1** validation failed (also for infeasible / unknown / error generator outcomes) ·
**2** unreadable or invalid input · **3** internal error (a bug, never a verdict on the layout).
HTTP: invalid input → 400, unexpected internal error → 500 JSON; the connection is never dropped without an answer.

## Pipeline

`spec.py` (validate input, tag provenance) → `generator.py` (`generate_layout`: pre-checks, then baseline **or**
`cpsat.py`) → `validator.py` (independent re-check of the produced rectangles; the only judge) → `report.py`.

## Generators (`spec.generator.method`)

| Method | What it is |
|---|---|
| `heuristic` (default) | Row-packing baseline, standard library only. Fast, deterministic, **not complete**: it can fail when a valid layout exists (e.g. the demo at 30 x 16 m). |
| `cpsat` | OR-Tools CP-SAT on an integer grid (`generator.grid_m`, default 0.1 m): positions and sizes, building boundary, `AddNoOverlap2D`, exact area band, minimum dimensions, adjacency as "touching along a wall of at least `min_shared_edge_m`". Model documented in the `cpsat.py` docstring. |

Settings: `method`, `grid_m` (0.01–1), `objective`, `time_limit_s` (default 20, covers the whole call incl. pre-check, hint and relaxation),
`deterministic_time_limit_s` (default off), `num_workers` (default 1), `seed` (default 1) and `model_options` (default `[]`).
Settings are modelling choices (tag `assumption`).

**Objectives.** `feasibility` (default; fastest; layouts are valid but loose) · `min_area_deviation` · `min_bbox_perimeter` / `min_bbox_area`
(compactness: the bounding box of all rooms is minimised, over the unchanged room-area, dimension, boundary, no-overlap and adjacency constraints;
the validator still judges). Compactness objectives usually run to the time limit and report `FEASIBLE` with a bound, not `OPTIMAL`; they can
need more time than `feasibility` to find a first layout.

**Determinism (measured, this machine only; see `benchmarks/runs/e7_*.json`).** One worker + fixed seed gave the identical layout and status in every
repeat (same process and fresh processes) *when the search finished before the limit*; a longer limit changed nothing; a different seed changed
the layout. When a **wall-clock** limit cuts the search short (typical with a compactness objective) identical inputs can give different layouts or
statuses (one case: 6 layouts in 6 runs). For reproducible cut-offs set `deterministic_time_limit_s` (OR-Tools "deterministic time", a work
count) and a generous `time_limit_s`. No claim is made about other machines, Python or OR-Tools versions.

**`model_options`** (opt-in search variants, sorted/de-duplicated; none changes which layouts the model accepts - see `tests/test_cpsat_options.py`):
`tight_domains`, `linear_adjacency`, `cumulative_cuts`, `mirror_symmetry`, `twin_symmetry`, `heuristic_hint`, `core_first` (definitions in the
`cpsat.py` docstring). **Measured on the hardest saved specs (9 specs with one seed; 7 of them with 5 seeds each) none raised the solve rate beyond run-to-run noise; none is on by default.**
`core_first` is the one with a distinct benefit: it can prove `infeasible_on_grid` from a relaxation (rooms with an adjacency requirement only), which
turned benchmark case 15 from UNKNOWN into a proof in about 3 s; it also costs part of the time budget, and on the held-out specs it lost 2 solves.

### Status semantics

| Generation status | Meaning |
|---|---|
| `placed` | A candidate was produced. **Not yet a success**: the validator decides. A candidate that fails validation is reported as a failure (with a note for CP-SAT). |
| `infeasible` | Proven impossible in continuous space by an arithmetic pre-check (tolerance-aware total area, minimum dimensions, shared wall longer than the building). |
| `infeasible_on_grid` | CP-SAT proved the **discretised model** infeasible. Says nothing about layouts with off-grid coordinates. |
| `unknown` | CP-SAT stopped without a layout or proof (e.g. time limit). **Never** an infeasibility claim. |
| `error` | Configuration/modelling error (`MODEL_INVALID`), including OR-Tools not installed. |

`solver.status` is `OPTIMAL` (proved optimal for the stated objective, in the grid model), `FEASIBLE` (candidate found, optimality not
proved; also what `objective: feasibility` reports, since there is nothing to optimise), `INFEASIBLE`, `UNKNOWN` or `MODEL_INVALID`;
`solver.raw_status` keeps OR-Tools' own name.

### Grid approximations (CP-SAT)

Always stricter than the validator, never looser: coordinates and sizes are multiples of `grid_m`; the building is floored to whole
cells; minimum dimension and minimum shared wall are rounded **up** to a cell; the area band is exact (±`area_rel_tol` of the required
area, converted with exact decimal arithmetic). A valid off-grid layout can therefore be missed; a result the model accepts is still
re-checked by the validator. Each result lists the approximations that applied.

## Files

| File | Purpose |
|---|---|
| `examples/synthetic_osd_demo.json`, `…_30m.json` | Synthetic 24 x 16 m (and 30 x 16 m) building, 14 rooms, 8 adjacency requirements |
| `pharma_layout/spec.py` | Input validation (all errors at once; raises only `SpecError`, fuzz-tested with the audit payloads), defaults, provenance tags |
| `pharma_layout/generator.py` | `generate_layout`, tolerance-aware `precheck`, row-packing baseline |
| `pharma_layout/cpsat.py` | CP-SAT generator, status mapping, `check_fixed_layout` (encoding test hook). Imports OR-Tools lazily |
| `pharma_layout/validator.py` | Rules V-01…V-08; imports neither generator; enforced by a test |
| `pharma_layout/report.py`, `pipeline.py`, `server.py`, `__main__.py`, `static/index.html` | Report, glue, local server, CLI, UI |
| `tests/` | Unit, regression (`test_audit_regressions.py`), CP-SAT acceptance (`test_cpsat.py`), live HTTP/CLI tests |
| `benchmarks/compare_generators.py`, `results.json` | Baseline vs CP-SAT on identical specs; recorded run (kept unchanged) |
| `benchmarks/specs/`, `specs_holdout/` | The 23 benchmark specs (**reconstructed** from the fixed seeds: the original run did not save them; verified against the recorded outcomes by `verify_specs.py`) and 14 held-out specs (seeds 101–114) |
| `benchmarks/experiment.py`, `determinism.py`, `run_phase3_*.sh`, `summarize*.py`, `diagnostics/` | Phase-3 experiments (outside the unit-test suite); each run writes a new file to `benchmarks/runs/` and never overwrites |
| `benchmarks/certificates/` | Validator-confirmed layouts proving specific benchmark specs feasible (re-checked by `tests/test_certificates.py`, no solver needed) |
| `benchmarks/PHASE3_REPORT.md` | Measured results, with sample sizes and limits |
| `requirements-cpsat.txt` | Optional dependency pin |

## Traceability view

Every report has a compact table *Traceability: requirement to check to evidence* (ID, requirement and value, provenance tag, status and
explanation, missing evidence). It is derived only from the validator results. It states **Verified external sources used: 0**: all values are
synthetic demo values, modelling assumptions or user input, and nothing is checked against a regulation or standard. `demo_evidence/` holds
the reports of the demo run (24 m and 30 m pass; heuristic at 30 m fails; 18 m proven infeasible; a 30-room spec UNKNOWN).

## Validator rules

Axis-aligned rectangles; x right, y down, origin top-left, metres. Epsilon 1e-6 m (absolute).

| Rule | Check |
|---|---|
| V-01 | Every room has exactly one well-formed placement |
| V-02 | Smallest accepted total area (Σ required × (1 − tol)) ≤ building area |
| V-03 | Width and height > 0 |
| V-04 | Room inside the building boundary |
| V-05 | No two rooms overlap (interior intersection) |
| V-06 | Placed area within ± tolerance of required area (default ±2 %; 1e-9 relative slack for float round-off only) |
| V-07 | Shorter side ≥ the room's `min_dim_m` (if given) |
| V-08:ADJ-xx | Interiors disjoint **and** shared boundary ≥ `min_shared_edge_m` (default 1.0 m). Corner contact or a gap does **not** count. |

## Four kinds of information (kept separate in the report)

1. **User requirements** — values you edited (tag `user`).
2. **Synthetic demo values** — shipped example (tag `synthetic_demo`).
3. **Assumptions** — tolerances, generator settings, defaults I chose (tag `assumption`); tracked per field.
4. **Not implemented** — regulatory/process requirements listed as out of scope (OOS-01…07). No standard or clause is cited.

## Known limitations

- The baseline heuristic still fails where a valid layout exists (use `cpsat`); the report says so when it fails.
- CP-SAT: grid approximations above; `UNKNOWN` happens (8 of 37 specs at a 20 s limit with the default model, all with 12–30 rooms; see
  `benchmarks/PHASE3_REPORT.md`), and it is mostly seed luck for 17–20 rooms (the same spec solves under some seeds and not others). Two 30-room specs
  stayed UNKNOWN even at 120 s with 1 and with 2 workers: feasibility is open. `feasibility` layouts are valid but loose; compactness objectives help
  (bounding box about 1.01–1.02 x the room area instead of about 1.5–1.7) but run to the time limit and are not proven optimal; no flow objective;
  adds a heavy optional dependency; at most 30 rooms. A coarser grid is not a remedy for UNKNOWN: with the default +-2 % area band it is usually
  infeasible at once.
- A grid-infeasible result is not a proof for off-grid layouts, and "no layout found" by any method other than a pre-check is not a proof of infeasibility.
- No corridors, doors, airlocks, personnel/material flow, pressure cascades, or room classification. "Adjacent" means a shared wall, not a connection.
- Rooms without `min_dim_m` have no shape limit (thin slivers can pass).
- Provenance tags are client-asserted (editing a number in the JSON while leaving `synthetic_demo` keeps that label); tags are per room, not per field;
  a field you touch stays tagged `user` even if you type the original value back; removing a room is not recorded as a change.
- Local single-user dev server: no authentication or HTTPS. Do not expose it. Not a git repository.

## POC workflow (hackathon demo): alternatives, comparison and indicative cost

UI button **Compare alternatives & estimate cost** (`POST /api/alternatives`) runs up to three *existing* generator configurations in parallel
(heuristic; CP-SAT feasibility; CP-SAT `min_bbox_area` with a deterministic limit), each through the normal pipeline and the independent validator.
Identical layouts are shown once; candidates that produce no layout are listed as absent (never as proven infeasible unless the pre-check/grid proof says so).
Ranking: PASS layouts first, then score = validity 60 + compactness 25 + area accuracy 15 (documented weights, a ranking aid only).
`pharma_layout/cost.py` gives an **illustrative** TIC in USD with a 0.80x-1.35x band: all rates, equipment allowances and percentages are **invented
demo assumptions, not quotations or sourced market data** (formulas, exclusions and assumptions are printed in the report). The plan is a conceptual 2D
drawing: no IFC/BIM, no 3D, no equipment placement or flow data. No LLM is connected (natural-language brief intake is future work). Tests: `tests/test_alternatives.py`.
