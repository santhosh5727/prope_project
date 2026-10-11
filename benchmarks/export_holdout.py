"""Held-out specs for the Phase-3 comparison: NEW seeds in the same four random families as the saved benchmark.

The seeds below were fixed on 2026-10-11 before any configuration comparison was finished and are never changed after seeing
results. They are used only to CONFIRM a configuration chosen on benchmarks/specs, never to choose it.
Writes benchmarks/specs_holdout/NN_<case>.json + MANIFEST.json (same format as benchmarks/specs/MANIFEST.json, indices 100+).
"""
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from compare_generators import random_case

FAMILIES = ((8, 24, 16, (101, 102, 103)), (12, 30, 24, (104, 105, 106, 107)), (20, 36, 24, (108, 109, 110, 111)), (30, 30, 24, (112, 113, 114)))
out = HERE / "specs_holdout"; out.mkdir(exist_ok=True)
manifest = []
for n, W, H, seeds in FAMILIES:
    for sd in seeds:
        name = f"random n={n} {W}x{H} seed={sd}"; f = f"{sd}_n{n}_{W}x{H}.json"
        text = json.dumps(random_case(sd, n, W, H), indent=1, sort_keys=True) + "\n"
        (out / f).write_text(text)
        manifest.append({"index": sd, "case": name, "file": f, "sha256": hashlib.sha256(text.encode()).hexdigest()})
(out / "MANIFEST.json").write_text(json.dumps({"provenance": "HELD-OUT specs, new seeds 101-114, same generator as benchmarks/compare_generators.random_case", "specs": manifest}, indent=1) + "\n")
print(f"wrote {len(manifest)} held-out specs")
