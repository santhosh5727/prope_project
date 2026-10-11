"""Traceability table in the report: derived from validator results only, standard library only (heuristic generator)."""
import re
import unittest

from pharma_layout.pipeline import run_pipeline
from tests.helpers import demo_raw


def section(html: str) -> str:
    return html.split("Traceability: requirement to check to evidence", 1)[1].split("Validation rules (implemented", 1)[0]


class Traceability(unittest.TestCase):
    def run_demo(self, width):
        raw = demo_raw(); raw["building"]["width_m"] = width; raw["generator"] = {"method": "heuristic"}
        return run_pipeline(raw)

    def test_every_rule_appears_with_status_provenance_and_evidence_gap(self):
        res = self.run_demo(24)
        sec = section(res["html"])
        ids = [r["rule_id"] for r in res["validation"]["results"]]
        for rid in ids:
            self.assertIn(f"<b>{rid}</b>", sec)
        self.assertEqual(sec.count("<tr>"), len(ids) + 1)               # header + one row per rule
        self.assertIn("Verified external sources used: 0", sec)
        self.assertIn("Missing evidence", sec)
        self.assertIn("synthetic demo", sec); self.assertIn("assumption", sec)
        self.assertIn("not GMP or regulatory compliance", sec)

    def test_failures_are_shown_as_failures_and_no_compliance_claim_is_made(self):
        res = self.run_demo(30)                                          # the baseline heuristic fails here (AUD-07)
        self.assertEqual(res["validation"]["overall"], "FAIL")
        sec = section(res["html"])
        self.assertIn('class="res FAIL"', sec)
        self.assertNotRegex(sec.lower(), r"(?<!not )(gmp|regulatory) compliant|complies with")

    def test_html_in_values_is_escaped(self):
        raw = demo_raw(); raw["rooms"][0]["id"] = "<b>X</b>"; raw["adjacency"] = []; raw["generator"] = {"method": "heuristic"}
        sec = section(run_pipeline(raw)["html"])
        self.assertNotIn("<b>X</b>", sec)


if __name__ == "__main__":
    unittest.main()
