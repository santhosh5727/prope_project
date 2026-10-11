"""POC: alternatives, ranking, cost model and the /api/alternatives endpoint. Heuristic-only paths run without OR-Tools."""
import json, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from pharma_layout import alternatives as alt, cost
from pharma_layout.cpsat import capabilities
from pharma_layout.pipeline import run_pipeline
from pharma_layout.spec import validate_spec
from tests.helpers import demo_raw

HAS = capabilities()["cpsat"]


def heuristic_only(raw):
    with mock.patch.object(alt, "capabilities", lambda: {"cpsat": False, "reason": "test"}):
        return alt.build_alternatives(raw)


class Cost(unittest.TestCase):
    def setUp(self):
        raw = demo_raw(); raw["generator"] = {"method": "heuristic"}
        res = run_pipeline(raw)
        self.est = cost.estimate(res["spec"], res["generation"]["rooms"])

    def test_band_ordering_and_labels(self):
        t = self.est["total"]
        self.assertLess(t["low"], t["base"]); self.assertLess(t["base"], t["high"])
        self.assertIn("illustrative", self.est["currency"].lower())
        self.assertTrue(self.est["exclusions"]); self.assertTrue(self.est["assumptions"])

    def test_lines_sum_to_total_and_carry_formulas(self):
        self.assertAlmostEqual(sum(l["base"] for l in self.est["lines"]), self.est["total"]["base"], delta=1.0)
        for l in self.est["lines"]:
            self.assertTrue(l["formula"]); self.assertLessEqual(l["low"], l["base"]); self.assertLessEqual(l["base"], l["high"])
        self.assertTrue(self.est["drivers"])


class Alternatives(unittest.TestCase):
    def test_heuristic_only_is_one_real_candidate(self):
        a = heuristic_only(demo_raw())
        self.assertEqual(len(a["shown"]), 1); self.assertEqual(a["shown"][0]["rank"], 1)
        self.assertIsNotNone(a["spec"]); self.assertIsNotNone(a["cost"])
        html = alt.render_alternatives(a)
        self.assertIn("Indicative Total Investment Cost", html); self.assertIn("not GMP", html)
        self.assertIn("no AI / LLM is connected", html)

    def test_weights_documented_and_sum_to_100(self):
        self.assertEqual(sum(alt.WEIGHTS.values()), 100)
        a = heuristic_only(demo_raw()); html = alt.render_alternatives(a)
        for k in alt.WEIGHTS:
            self.assertIn(k, html)

    def test_no_candidate_is_shown_twice(self):
        a = heuristic_only(demo_raw())
        keys = [alt._layout_key(c["res"]["generation"]["rooms"]) for c in a["shown"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_infeasible_brief_shows_nothing_as_a_layout_and_never_says_unknown_is_infeasible(self):
        raw = demo_raw(); raw["building"]["width_m"] = 18
        a = heuristic_only(raw)
        self.assertEqual(a["shown"], []); self.assertIsNone(a["selected"])
        html = alt.render_alternatives(a)
        self.assertNotIn("Indicative Total Investment Cost", html)

    @unittest.skipUnless(HAS, "OR-Tools not installed")
    def test_cpsat_alternatives_distinct_and_ranked_pass_first(self):
        a = alt.build_alternatives(demo_raw())
        self.assertGreaterEqual(len(a["shown"]), 2)
        keys = [alt._layout_key(c["res"]["generation"]["rooms"]) for c in a["shown"]]
        self.assertEqual(len(keys), len(set(keys)))
        seen_fail = False
        for c in a["shown"]:  # PASS candidates must precede non-PASS
            if c["m"]["overall"] != "PASS": seen_fail = True
            else: self.assertFalse(seen_fail)
        scores = [c["m"]["score"] for c in a["shown"] if c["m"]["overall"] == "PASS"]
        self.assertEqual(scores, sorted(scores, reverse=True))


class Endpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pharma_layout import server
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def post(self, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/alternatives", json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_invalid_input_is_400(self):
        code, data = self.post({"building": {"width_m": -1}})
        self.assertEqual(code, 400); self.assertFalse(data["ok"]); self.assertTrue(data["errors"])

    def test_valid_input_returns_html(self):
        with mock.patch.object(alt, "capabilities", lambda: {"cpsat": False, "reason": "test"}):
            code, data = self.post(demo_raw())
        self.assertEqual(code, 200); self.assertTrue(data["ok"]); self.assertIn("Indicative Total Investment Cost", data["html"])


if __name__ == "__main__":
    unittest.main()
