"""Diagnostic (not a test): solve a saved spec with its isolated rooms (no adjacency requirement) REMOVED.
Removing rooms is a relaxation: if the relaxed model is INFEASIBLE the full model is too (on the same grid); if it is feasible
that says nothing certain about the full spec. Usage: relax_isolated.py CASE_INDEX [time_limit_s] [seed]"""
import json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import experiment as ex

idx = int(sys.argv[1]); tl = float(sys.argv[2]) if len(sys.argv) > 2 else 60; seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
name, raw = {i: (n, r) for i, n, r in ex.load_specs()}[idx]
used = {x for a in raw["adjacency"] for x in (a["a"], a["b"])}
raw["rooms"] = [r for r in raw["rooms"] if r["id"] in used]
raw["generator"] = {"time_limit_s": tl, "seed": seed}
r = ex.run_case(idx, name + f" [relaxed: {len(raw['rooms'])} rooms in adjacency graph only]", raw, "cpsat", {})
print({k: r[k] for k in ("case", "generation", "solver_status", "raw_status", "validator", "wall_s")})
