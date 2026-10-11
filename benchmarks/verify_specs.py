"""Check that benchmarks/specs/*.json (a RECONSTRUCTION) reproduce the outcomes recorded in benchmarks/results.json.

Heuristic: generation status + validator verdict must match for all 23 cases (deterministic, no solver).
CP-SAT (--cpsat): generation status, solver status and validator verdict must match for every case that did not
UNKNOWN in the recorded run (UNKNOWN cases are the subject of the experiments, not of this check). Timing is not compared.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from pharma_layout.pipeline import run_pipeline

man = json.loads((HERE / "specs" / "MANIFEST.json").read_text())["specs"]
rec = json.loads((HERE / "results.json").read_text())["rows"]
do_cp = "--cpsat" in sys.argv
bad = 0
for m, row in zip(man, rec):
    assert m["case"] == row["case"], (m["case"], row["case"])
    raw = json.loads((HERE / "specs" / m["file"]).read_text())
    h = run_pipeline(json.loads(json.dumps(raw)), method="heuristic")
    got = (h["generation"]["status"], h["validation"]["overall"]); want = (row["heuristic"]["generation"], row["heuristic"]["validator"])
    line = f"{m['index']:02d} heuristic {'ok ' if got == want else 'DIFF'} {got}"
    bad += got != want
    if do_cp and row["cpsat"]["solver_status"] != "UNKNOWN":
        c = run_pipeline(json.loads(json.dumps(raw)), method="cpsat")
        sol = c["generation"].get("solver") or {}
        got = (c["generation"]["status"], sol.get("status"), c["validation"]["overall"])
        want = (row["cpsat"]["generation"], row["cpsat"]["solver_status"], row["cpsat"]["validator"])
        line += f" | cpsat {'ok ' if got == want else 'DIFF'} {got}"
        bad += got != want
    print(line, flush=True)
print("mismatches:", bad)
sys.exit(1 if bad else 0)
