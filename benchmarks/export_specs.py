"""Write the 23 benchmark specs of compare_generators.py to benchmarks/specs/NN_<slug>.json plus a MANIFEST.json.

RECONSTRUCTION NOTICE: the original run (benchmarks/results.json) did not store its input specs. These files are
regenerated from the fixed definitions in compare_generators.cases() (fixed seeds, no randomness beyond random.Random(seed)).
They are therefore a reconstruction, not the original bytes. benchmarks/verify_specs.py checks the reconstruction
against the recorded results.json rows (heuristic outcomes for all 23 cases; CP-SAT outcomes for the cases that finished).
"""
import hashlib, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from compare_generators import cases

out = HERE / "specs"; out.mkdir(exist_ok=True)
manifest = []
for n, (name, raw) in enumerate(cases()):
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    f = f"{n:02d}_{slug}.json"
    text = json.dumps(raw, indent=1, sort_keys=True) + "\n"
    (out / f).write_text(text)
    manifest.append({"index": n, "case": name, "file": f, "sha256": hashlib.sha256(text.encode()).hexdigest()})
(out / "MANIFEST.json").write_text(json.dumps(
    {"provenance": "RECONSTRUCTED from compare_generators.cases() on 2026-10-11; the original run did not save its specs",
     "specs": manifest}, indent=1) + "\n")
print(f"wrote {len(manifest)} specs to {out}")
