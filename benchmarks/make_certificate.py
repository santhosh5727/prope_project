"""Store a validator-confirmed layout for a saved spec as a FEASIBILITY CERTIFICATE (benchmarks/certificates/NN.json).

A certificate turns "the solver found something once" into a fact anyone can re-check without a solver:
tests/test_certificates.py re-validates every stored layout with the independent validator.
  ./.venv/bin/python benchmarks/make_certificate.py CASE_INDEX [--seed N] [--set k=v ...]
Refuses to store a layout the validator does not PASS."""
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import experiment as ex
from pharma_layout.pipeline import run_pipeline

ap = argparse.ArgumentParser(); ap.add_argument("case", type=int); ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--set", action="append", default=[]); ap.add_argument("--specs", default="specs"); a = ap.parse_args()
over = {k: ([x for x in v.split(",") if x] if k == "model_options" else ex.coerce(v)) for k, v in (s.split("=", 1) for s in a.set)}
name, raw = {i: (n, r) for i, n, r in ex.load_specs(a.specs)}[a.case]
raw["generator"] = {"method": "cpsat", "seed": a.seed, **over}
res = run_pipeline(json.loads(json.dumps(raw)))
g, v = res["generation"], res["validation"]
if g["status"] != "placed" or v["overall"] != "PASS":
    sys.exit(f"no certificate: generation={g['status']} solver={(g.get('solver') or {}).get('status')} validator={v['overall']}")
out = HERE / "certificates"; out.mkdir(exist_ok=True)
f = out / f"{a.specs}_{a.case:03d}.json"
f.write_text(json.dumps({"case": name, "spec_folder": f"benchmarks/{a.specs}", "spec_index": a.case, "found_with": raw["generator"],
                         "validator_overall": v["overall"], "rooms": [{k: p[k] for k in ("id", "x", "y", "w", "h")} for p in g["rooms"]]}, indent=1) + "\n")
print("wrote", f)
