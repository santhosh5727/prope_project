# Phase 3 - CP-SAT reliability and layout quality (measured 2026-10-11)

Everything below is computed from files in `benchmarks/runs/` (one file per run, never overwritten) except where a sentence says otherwise.
Environment: 2 CPUs, Python 3.13, OR-Tools 9.15.6755. Defaults unless stated: grid 0.1 m, 1 worker, seed 1, 20 s, objective `feasibility`.
**Samples are small** (23 saved + 14 held-out random/demo specs, mostly one seed); differences of one or two specs are within run-to-run noise
(see E2). Nothing here is a general performance claim, and no regulatory or GMP claim is made.

## 1. Inputs: what was and was not saved
`benchmarks/results.json` (kept byte-identical) holds outcomes only, **not the specs**. The 23 specs in `benchmarks/specs/` are a
**reconstruction** from the fixed definitions/seeds in `compare_generators.cases()`. Check (`verify_specs.py --cpsat`): heuristic outcome matches the
recorded row for 23/23 specs and the CP-SAT generation/solver/validator outcome matches for the 19 specs that were not UNKNOWN: 0 mismatches. That is strong
evidence, not proof of byte-identical inputs. The 14 held-out specs (seeds 101-114) were generated before configurations were compared.

## 2. The four UNKNOWN cases
Reproduced exactly (grid 0.1, feasibility, 1 worker, seed 1, 20 s): all four UNKNOWN at 20.01 s (`rerun_unknown_baseline.json`). UNKNOWN is not treated as a verdict anywhere.

| case | what is now known | evidence |
|---|---|---|
| 15 (n=12, 30x24) | **Infeasible on the 0.1 m grid.** The model restricted to the 9 rooms named in adjacency requirements is proven INFEASIBLE in about 3 s; removing rooms only relaxes a model, so the full model is infeasible on the grid. Not a proof for off-grid layouts. The full model could not prove this in 20 s because of the 3 unconstrained rooms. | `diagnostics/relax_isolated.py 15`; `core_first` decides it in 3/3 seeds (`e4_core_first.json`) |
| 20 (n=20, 36x24) | **Feasible.** Solved in 2 of 5 seeds (base) and by other options; the layout is stored as a certificate and re-validated by `tests/test_certificates.py`. Seed 1 times out; the UNKNOWN was seed luck. | `certificates/specs_020.json`, `e2_*.json` |
| 21, 22 (n=30) | **Open.** UNKNOWN in every run (20 runs at 20 s over 4 configurations; 60 s on the adjacency-only relaxation; 120 s with 1 worker; 120 s with 2 workers). Neither feasible nor infeasible is established. | `e2_*`, `e5_long_*.json`, `diagnostics/` |

## 3. Techniques, measured individually (E1 one seed; E2 five seeds)
E1 (seed 1, 9 specs: the 4 UNKNOWN + 5 the base solves in 5-12 s): solved = base 5, tight_domains 5, linear_adjacency 5, cumulative_cuts 4, mirror_symmetry 6, twin_symmetry 5, heuristic_hint 5.
Because one run per option is dominated by search luck, E2 repeated base / mirror / cumulative / linear over seeds 1-5 on 7 of those specs (2 processes ran concurrently on the 2 CPUs; all configurations saw the same load):

* **tight_domains** - no effect: identical layout in 9/9 specs, times within 0.35 s (the solver's presolve already derives these bounds). Dropping the unused deviation column changed nothing measurable.
* **linear_adjacency**, **cumulative_cuts**, **mirror_symmetry** - mixed per spec (e.g. cumulative_cuts: median 3.4 s vs 9.1 s on spec 19 but 2/5 vs 4/5 solved on spec 18). Totals over 35 runs: base 15, mirror 14, cumulative 14, linear 10. **No option is distinguishable from seed noise; linear_adjacency was worst, not significantly.**
* **twin_symmetry** - applies only to identical rooms with no adjacency: in 6 of the 37 specs (the demo variants, one pair each), in none of the random ones. In E1 it changed the result only on spec 3 (8.3 s -> 3.6 s, one run, different layout) - not evidence of a benefit.
* **core_first** - proves case 15 infeasible on the grid (see above); on specs with a feasible core it spends part of the budget: 8/21 solved over 3 seeds vs 10/21 for base on the same 7 specs, and on the held-out set 8/14 vs 10/14 (it lost 106 and 108). So it is a proof tool, not a speed-up.
* Seed luck is the dominant factor for 17-20 rooms: the same spec solves under some seeds and not others (E2 tables below).

All options are **sound by test** (`tests/test_cpsat_options.py`): pure-encoding options accept exactly the layouts the base model and the validator accept (pinned-variable differential tests); symmetry options leave feasibility unchanged on random specs; 15 deliberate mutants of the new code were run against these tests (scratch harness, not committed) - the first run of 11 let 2 survive, which exposed gaps (thin-room adjacency, twin grouping); after adding tests all 15 are caught on the final code.

## 4. Compactness objective and warm start (E6; 11 specs the base model solves quickly; every layout passed the validator, 66/66)
* Feasibility layouts: bounding box / total room area has median 1.54 (range 1.00-2.29). With `min_bbox_area` the median is 1.01 (range 1.00-1.01), `min_bbox_perimeter` 1.00-1.03. In the larger comparison (section 6) the paired result is D <= A in 23 of 24 specs.
* Cost: compactness runs use the whole time limit and report FEASIBLE with a gap (gap between solution and bound: area objective about 0.3-2.2 %, perimeter objective after the added bound about 0.3-3.1 % - the perimeter bound was previously 80 against 346, **a defect found and fixed**), OPTIMAL only for the trivial spec. They can also need longer than `feasibility` to find a first layout (the demo returned UNKNOWN at a 3 s limit with `min_bbox_area`).
* The heuristic's own layout is valid only on 3 of the 11 specs (0, 3, 7), and there it is already perfectly compact (ratio 1.00). `heuristic_hint` adds a median 1.9 s (the heuristic runs first), left the layout unchanged on 10/11 specs under `feasibility` and 11/11 under the perimeter objective; under `min_bbox_area` it gave 1.0126 -> 1.0081 (spec 0) and 1.0074 -> 1.0278 (spec 3). **No consistent benefit.** For the 4 UNKNOWN cases the heuristic layout is invalid, so a valid warm start does not exist there (a hint from an invalid layout was tried in E1: no effect).

## 5. Determinism (E7; this machine, Python and OR-Tools build only)
* Base model, 4 specs, 10 runs each (5 in one process, 5 in fresh processes with different `PYTHONHASHSEED`): **one layout hash and one solver status per spec**; wall time varied by up to about 15 % between runs. A 60 s limit gives the same layout as 20 s (3 specs). Seed 2 gives a different layout.
* When a wall-clock limit cuts an optimising search short, identical input gave **different layouts on the same machine** (0.7 s limit: 6 layouts in 6 runs for one spec; 1.5 s: 2 and 4 layouts). The documented determinism holds only when the limit is not reached.
* With the new `deterministic_time_limit_s` (work-based) 6 identical runs gave one layout and one status in two specs and two limits (0.3, 1.0). Nothing is claimed for other platforms or OR-Tools versions.

## 6. Baseline heuristic vs CP-SAT, same specs
A = shipped default; B = A + `core_first`; C = B + `min_bbox_area`; D = `min_bbox_area` alone. "UNKNOWN" is never counted as infeasible.

| specs | method | specs | validator PASS | placed but FAIL | UNKNOWN | proven infeasible* | median s (solved) | median bbox / room area (solved) | total s |
|---|---|---|---|---|---|---|---|---|---|
| 23 saved (reconstructed) | baseline heuristic | 23 | 3 | 19 | 0 | 1 | 0.19 | 1.00 | 11 |
| 23 saved (reconstructed) | CP-SAT A: default (feasibility) | 23 | 16 | 0 | 4 | 3 | 1.54 | 1.49 | 137 |
| 23 saved (reconstructed) | CP-SAT B: A + core_first | 23 | 16 | 0 | 3 | 4 | 4.14 | 1.49 | 165 |
| 23 saved (reconstructed) | CP-SAT C: B + min_bbox_area | 23 | 16 | 0 | 3 | 4 | 20.01 | 1.01 | 343 |
| 23 saved (reconstructed) | CP-SAT D: min_bbox_area only | 23 | 16 | 0 | 4 | 3 | 20.01 | 1.01 | 360 |
| 14 held-out | baseline heuristic | 14 | 0 | 14 | 0 | 0 | - | - | 12 |
| 14 held-out | CP-SAT A: default (feasibility) | 14 | 10 | 0 | 4 | 0 | 1.36 | 1.67 | 122 |
| 14 held-out | CP-SAT B: A + core_first | 14 | 8 | 0 | 6 | 0 | 1.76 | 1.67 | 149 |
| 14 held-out | CP-SAT C: B + min_bbox_area | 14 | 9 | 0 | 5 | 0 | 20.01 | 1.02 | 280 |
| 14 held-out | CP-SAT D: min_bbox_area only | 14 | 9 | 0 | 5 | 0 | 20.01 | 1.01 | 280 |

*pre-check (continuous space) or on the 0.1 m grid; see the status semantics in the README.


Reading it: the heuristic passes the validator on 3/37 specs (all simple), A on 26/37, D on 25/37. UNKNOWN: A 8/37. The A-vs-D difference of one spec is noise.
Compactness of solved specs: A median 1.49 (saved) / 1.67 (held-out); D 1.01 / 1.01. Where the heuristic is valid (3 specs) its layout is at least as compact as D's (ratio 1.00 vs 1.0126 / 1.0074 / 1.0).

### E2 detail (five seeds)

| case | base | mirror_symmetry | cumulative_cuts | linear_adjacency |
|---|---|---|---|---|
| 15 | 0/5 | 0/5 | 0/5 | 0/5 |
| 17 | 4/5 (median 8.5 s) | 3/5 (median 4.1 s) | 4/5 (median 5.3 s) | 3/5 (median 8.0 s) |
| 18 | 4/5 (median 15.7 s) | 3/5 (median 18.9 s) | 2/5 (median 11.7 s) | 2/5 (median 11.2 s) |
| 19 | 5/5 (median 9.1 s) | 5/5 (median 8.7 s) | 5/5 (median 3.4 s) | 5/5 (median 5.0 s) |
| 20 | 2/5 (median 12.0 s) | 3/5 (median 17.9 s) | 3/5 (median 10.4 s) | 0/5 |
| 21 | 0/5 | 0/5 | 0/5 | 0/5 |
| 22 | 0/5 | 0/5 | 0/5 | 0/5 |
| **all** | **15/35** | **14/35** | **14/35** | **10/35** |


## 7. Defects confirmed and fixed (each has a regression test in `tests/test_cpsat_options.py` / `test_certificates.py`)
1. `compare_generators.py` ran `main()` on import (would silently re-run the benchmark and overwrite `results.json`) - now guarded; AST test.
2. Hints from two sources named the same variable -> OR-Tools rejected the model -> MODEL_INVALID for a feasible spec (found by the all-options differential test).
3. `time_limit_s` did not cover the heuristic hint (22 s wall for a 20 s limit) - the limit now covers the whole call.
4. The UNKNOWN message advised "a coarser grid", which made all four UNKNOWN specs infeasible-on-grid at once (empty area band) - message corrected.
5. The `min_bbox_perimeter` lower bound was far too weak (80 vs 346) - redundant sound cut added (`Wb + Hb >= k`).
6. Documented determinism understated the wall-clock hazard (section 5) - work-based limit added and documented.

## 8. Best configuration and what remains
* **Find a valid layout fast:** the shipped default (A): 26/37 solved, median 1.5 s when solved.
* **Best layout quality at the same reliability:** D (`objective: min_bbox_area`, default model, `time_limit_s` >= 20; add `deterministic_time_limit_s` for reproducibility): 25/37 solved, bounding box about 1.01 x the room area instead of about 1.5-1.7, about 20 s per spec.
* **To decide infeasibility where unconstrained rooms exist:** add `core_first` (sound, grid-scoped); do not use it for speed.
* Remaining limitations: 8/37 specs are UNKNOWN with the default (case 15 now decided by `core_first`; 21, 22 and 4 held-out specs remain open); feasibility of the open specs is unknown; layouts are grid-restricted; compactness is a bounding-box measure only (no flow, no doors/corridors); no 30-room spec was solved (0 of 5, saved + held-out) at any setting tried; timings depend on this 2-CPU machine; seeds matter a lot, so single-run comparisons (including most of this report) overstate small differences; a multi-seed portfolio or longer limits were not implemented.

## 9. Reproduce
`./.venv/bin/python benchmarks/verify_specs.py --cpsat` (reconstruction check) · `benchmarks/run_phase3_e1.sh`, `e2`, `e5`, `e6`, `e7`, `e8`, `e8b` (each writes new files to `benchmarks/runs/`; they refuse to overwrite) · `python3 benchmarks/make_phase3_tables.py` (tables above).
