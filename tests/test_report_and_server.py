"""Report safety/honesty and the live HTTP API."""
import json
import re
import threading
import unittest
import urllib.error
import urllib.request

from pharma_layout.pipeline import run_pipeline
from pharma_layout.server import make_server
from tests.helpers import demo_raw


class ReportContent(unittest.TestCase):
    def test_user_text_is_html_escaped(self):
        raw = demo_raw()
        raw["rooms"][0]["name"] = "<script>alert(1)</script>"
        raw["rooms"][0]["id"] = 'X"><img src=x onerror=alert(2)>'
        raw["adjacency"][0]["a"] = raw["rooms"][0]["id"]
        html = run_pipeline(raw)["html"]
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)

    def test_report_separates_inputs_checks_and_out_of_scope(self):
        html = run_pipeline(demo_raw())["html"]
        for needle in ("V-01", "V-08:ADJ-01", "synthetic demo", "assumption", "NOT IMPLEMENTED", "OOS-01",
                       "not a regulatory or GMP compliance statement"):
            self.assertIn(needle, html)

    def test_user_edits_are_tagged_user_provided(self):
        raw = demo_raw(); raw["building"]["source"] = "user"
        self.assertIn("tag user", run_pipeline(raw)["html"])

    def test_tolerance_provenance_is_per_field(self):
        """Editing one tolerance must not relabel the others as user-provided (regression: found in browser check)."""
        from pharma_layout.validator import validate_layout
        from tests.helpers import result
        raw = demo_raw(); raw["tolerances"]["min_shared_edge_m"] = 2.0; raw["tolerances"]["user_fields"] = ["min_shared_edge_m"]
        res = run_pipeline(raw)
        v = res["validation"]
        src = lambda rule, name: next(i["source"] for i in result(v, rule)["inputs"] if i["name"] == name)
        self.assertEqual(src("V-08:ADJ-01", "min_shared_edge_m"), "user")
        self.assertEqual(src("V-06", "area_rel_tol"), "assumption")
        self.assertEqual(src("V-04", "eps"), "assumption")
        row = lambda name: re.search(rf"<td>{name}</td><td>[^<]*</td><td><span class=\"([^\"]*)\">([^<]*)</span>", res["html"]).groups()
        self.assertEqual(row("min_shared_edge_m"), ("tag user", "user-provided"))
        self.assertEqual(row("area_rel_tol"), ("tag", "assumption"))
        self.assertEqual(row("geom_eps_m"), ("tag", "assumption"))

    def test_no_regulation_or_standard_citations_are_emitted(self):
        html = run_pipeline(demo_raw())["html"]
        self.assertIsNone(re.search(r"\bISO\b|\bCFR\b|EudraLex|\bAnnex\b|\bICH\b|Schedule M|\bTRS\b", html))


class HttpApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def post(self, body, raw=False):
        data = body if raw else json.dumps(body).encode()
        req = urllib.request.Request(self.base + "/api/run", data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_index_page_served_with_css_injected(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            page = r.read().decode()
        self.assertIn("Generate &amp; validate", page)
        self.assertNotIn("/*__CSS__*/", page)

    def test_example_endpoint(self):
        with urllib.request.urlopen(self.base + "/api/example", timeout=10) as r:
            self.assertEqual(len(json.loads(r.read())["rooms"]), 14)

    def test_run_demo_end_to_end(self):
        code, body = self.post(demo_raw())
        self.assertEqual((code, body["ok"], body["overall"]), (200, True, "PASS"))
        self.assertIn("<svg", body["html"])
        self.assertEqual(body["generation"]["status"], "placed")

    def test_edit_then_regenerate_changes_outcome(self):
        raw = demo_raw(); raw["building"]["width_m"] = 10
        code, body = self.post(raw)
        self.assertEqual((code, body["overall"], body["generation"]["status"]), (200, "FAIL", "infeasible"))
        raw["building"]["width_m"] = 24  # back to the demo size
        _, body2 = self.post(raw)
        self.assertEqual((body2["overall"], body2["generation"]["status"]), ("PASS", "placed"))

    def test_invalid_spec_gets_400_with_all_errors(self):
        raw = demo_raw(); raw["rooms"][0]["area_m2"] = -1; raw["building"]["height_m"] = None
        code, body = self.post(raw)
        self.assertEqual(code, 400)
        self.assertFalse(body["ok"])
        self.assertGreaterEqual(len(body["errors"]), 2)

    def test_non_json_body_gets_400(self):
        code, body = self.post(b"{not json", raw=True)
        self.assertEqual(code, 400)

    def test_unknown_path_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/etc/passwd", timeout=10)
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
