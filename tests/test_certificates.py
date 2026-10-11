"""Feasibility certificates: layouts stored in benchmarks/certificates/ must pass the independent validator on the saved spec.
No solver is involved, so this runs (and can fail) without OR-Tools. It pins facts such as "benchmark case 20 IS feasible"."""
import json
import unittest
from pathlib import Path

from pharma_layout.spec import validate_spec
from pharma_layout.validator import validate_layout

ROOT = Path(__file__).resolve().parent.parent / "benchmarks"


class Certificates(unittest.TestCase):
    def test_every_certificate_passes_the_validator(self):
        files = sorted((ROOT / "certificates").glob("*.json"))
        self.assertTrue(files, "no certificates stored")
        for f in files:
            c = json.loads(f.read_text())
            man = {m["index"]: m for m in json.loads((ROOT / Path(c["spec_folder"]).name / "MANIFEST.json").read_text())["specs"]}
            raw = json.loads((ROOT / Path(c["spec_folder"]).name / man[c["spec_index"]]["file"]).read_text())
            spec = validate_spec(raw)
            v = validate_layout(spec, c["rooms"])
            self.assertEqual(v["overall"], "PASS", (f.name, [r["explanation"] for r in v["results"] if r["result"] == "FAIL"]))
            self.assertEqual(len(c["rooms"]), len(spec["rooms"]))


if __name__ == "__main__":
    unittest.main()
