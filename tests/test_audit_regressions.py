"""Regression tests from the 2026-10-11 engineering audit.

Every AUD-nn below is a defect that was REPRODUCED by a script before it was written down here.
STATUS: AUD-01 .. AUD-06 are FIXED; their tests are ordinary regression tests (assertions unchanged from the audit).
AUD-07 concerns the row-packing BASELINE heuristic, which still has the limitation; its test keeps
``@unittest.expectedFailure`` (explicitly selecting method="heuristic"). The fix for AUD-07 is the CP-SAT generator, whose
acceptance test for the same 30 m case is in tests/test_cpsat.py. When the heuristic itself is improved, the unexpected
success will say so (unittest counts it as a failure) and the decorator must go.
Tests that always passed (controls and the 30 m certificate) pin facts the audit established.

  AUD-01  non-hashable values in `source` / adjacency endpoints escape validate_spec as TypeError
  AUD-02  integers too large for float escape validate_spec as OverflowError
  AUD-03  HTTP server drops the connection (no 400) for AUD-01/02 payloads and for deeply nested JSON
  AUD-04  V-02 says "no layout can satisfy all areas" although area tolerance (V-06) allows a fit
  AUD-05  generator pre-check says "infeasible" for a room that satisfies V-06/V-07 within tolerance
  AUD-06  V-06 has no floating-point slack: a room exactly at +2.0 % is rejected
  AUD-07  a valid layout exists at 30 x 16 m, but the baseline heuristic does not find it (CP-SAT does)
"""
import http.client
import json
import threading
import unittest

from pharma_layout.generator import generate_layout
from pharma_layout.pipeline import run_pipeline
from pharma_layout.server import make_server
from pharma_layout.spec import SpecError, validate_spec
from pharma_layout.validator import validate_layout
from tests.helpers import demo_raw, make_spec, rect, result


def _escapes_as_non_spec_error(raw):
    """None if validate_spec rejects/accepts cleanly, else 'TypeName: message' of the escaping exception."""
    try:
        validate_spec(raw)
    except SpecError:
        return None
    except Exception as e:  # noqa: BLE001 - this is exactly what we are probing for
        return f"{type(e).__name__}: {e}"
    return None


def _crash_payloads():
    out = {}
    d = demo_raw(); d["adjacency"][0]["a"] = ["MAL_IN"]; out["adjacency endpoint is a list"] = d
    d = demo_raw(); d["rooms"][0]["source"] = ["user"]; out["room source is a list"] = d
    d = demo_raw(); d["building"]["source"] = {}; out["building source is an object"] = d
    d = demo_raw(); d["tolerances"]["source"] = []; out["tolerances source is a list"] = d
    return out


class Aud01UnhashableValues(unittest.TestCase):
    def test_unhashable_source_or_endpoint_is_a_spec_error_not_a_crash(self):
        escaped = {name: e for name, raw in _crash_payloads().items() if (e := _escapes_as_non_spec_error(raw))}
        self.assertEqual(escaped, {})


class Aud02HugeIntegers(unittest.TestCase):
    def test_integer_too_large_for_float_is_a_spec_error_not_a_crash(self):
        escaped = {}
        for name, mutate in {
            "building width 10**400": lambda d: d["building"].__setitem__("width_m", 10 ** 400),
            "room area 10**400": lambda d: d["rooms"][0].__setitem__("area_m2", 10 ** 400),
            "area_rel_tol 10**400": lambda d: d["tolerances"].__setitem__("area_rel_tol", 10 ** 400),
        }.items():
            raw = demo_raw(); mutate(raw)
            if (e := _escapes_as_non_spec_error(raw)):
                escaped[name] = e
        self.assertEqual(escaped, {})


class Aud03ServerRobustness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server("127.0.0.1", 0)
        cls.srv.handle_error = lambda request, client_address: None  # keep expected tracebacks out of the test log
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def status_of(self, body: bytes):
        """HTTP status, or the exception name if the server closed the connection without answering."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.request("POST", "/api/run", body=body, headers={"Content-Type": "application/json"})
            return c.getresponse().status
        except Exception as e:  # noqa: BLE001
            return type(e).__name__
        finally:
            c.close()

    def test_control_plain_invalid_spec_gets_400(self):
        raw = demo_raw(); raw["rooms"][0]["area_m2"] = -1
        self.assertEqual(self.status_of(json.dumps(raw).encode()), 400)

    def test_control_server_survives_a_dropped_request(self):
        self.status_of(b"[" * 20000 + b"]" * 20000)  # whatever it answers, the next request must work
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/example"); self.assertEqual(c.getresponse().status, 200); c.close()

    def test_unhashable_value_gets_400(self):
        raw = demo_raw(); raw["adjacency"][0]["a"] = ["MAL_IN"]
        self.assertEqual(self.status_of(json.dumps(raw).encode()), 400)

    def test_deeply_nested_json_gets_400(self):
        self.assertEqual(self.status_of(b"[" * 20000 + b"]" * 20000), 400)


class Aud04TotalAreaVersusTolerance(unittest.TestCase):
    SPEC = make_spec([("A", 50.5), ("B", 50.5)], [("A", "B")], W=10, H=10)       # 101 m2 required, 100 m2 available
    LAYOUT = [rect("A", 0, 0, 10, 4.95), rect("B", 0, 4.95, 10, 4.95)]           # each 49.5 m2 = -1.98 %

    def test_control_layout_satisfies_every_rule_except_v02(self):
        v = validate_layout(self.SPEC, self.LAYOUT)
        others = {r["rule_id"]: r["result"] for r in v["results"] if r["rule_id"] != "V-02"}
        self.assertNotIn("FAIL", others.values(), others)
        self.assertEqual(result(v, "V-06")["result"], "PASS")  # areas ARE within the +-2 % tolerance

    def test_v02_does_not_reject_a_total_that_fits_within_area_tolerance(self):
        self.assertEqual(result(validate_layout(self.SPEC, self.LAYOUT), "V-02")["result"], "PASS")


class Aud05GeneratorPrecheckVersusTolerance(unittest.TestCase):
    SPEC = make_spec([("A", 8.9, 3.0)], W=10, H=10)  # a 3.0 x 3.0 room is 9.0 m2 = +1.1 %: inside +-2 % and >= min dim

    def test_control_hand_made_room_is_valid(self):
        self.assertEqual(validate_layout(self.SPEC, [rect("A", 0, 0, 3, 3)])["overall"], "PASS")

    def test_generator_does_not_call_a_feasible_room_infeasible(self):
        self.assertEqual(generate_layout(self.SPEC)["status"], "placed")


class Aud06AreaToleranceBoundary(unittest.TestCase):
    SPEC = make_spec([("A", 30)], W=20, H=10)

    def test_control_clearly_over_tolerance_fails(self):
        v = validate_layout(self.SPEC, [rect("A", 0, 0, 10.4, 3.0)])  # 31.2 m2 = +4 %
        self.assertEqual(result(v, "V-06")["result"], "FAIL")

    def test_area_exactly_at_plus_tolerance_passes(self):
        # 10.200000000000001 x 3.0 is +2.0 % up to float noise (dev = 0.02000000000000005). Found via a solver layout.
        v = validate_layout(self.SPEC, [rect("A", 0, 0, 10.200000000000001, 3.0)])
        self.assertEqual(result(v, "V-06")["result"], "PASS", result(v, "V-06")["explanation"])


# Valid layout for the demo requirements inside a 30 x 16 m building: the 24 m-wide layout from the generator,
# stored as literals so this certificate does not depend on the generator staying unchanged.
CERT_30M = [
    ("MAL_IN", 0.0, 0.0, 2.0, 4.5),
    ("STG_IN", 2.0, 0.0, 6.666666667, 4.5),
    ("DISP", 8.666666667, 0.0, 5.333333333, 4.5),
    ("GRAN", 14.0, 0.0, 10.0, 4.5),
    ("COAT", 0.0, 4.5, 7.128712871, 4.208333333),
    ("COMP", 7.128712871, 4.5, 5.940594059, 4.208333333),
    ("BLEND", 13.069306931, 4.5, 7.128712871, 4.208333333),
    ("MILL", 20.198019802, 4.5, 3.801980198, 4.208333333),
    ("WASH", 0.0, 8.708333333, 5.517241379, 3.625),
    ("CLEAN_EQ", 5.517241379, 8.708333333, 4.137931034, 3.625),
    ("PAL", 9.655172414, 8.708333333, 3.310344828, 3.625),
    ("STG_OUT", 12.965517241, 8.708333333, 5.517241379, 3.625),
    ("WASTE", 18.482758621, 8.708333333, 2.206896552, 3.625),
    ("IPC", 20.689655172, 8.708333333, 3.310344828, 3.625),
]


class Aud07ValidLayoutExistsAt30m(unittest.TestCase):
    def raw30(self):
        raw = demo_raw(); raw["building"]["width_m"] = 30
        return raw

    def test_certificate_proves_the_30m_spec_is_feasible(self):
        """Feasibility is established by construction, not inferred from a failed heuristic search."""
        spec = validate_spec(self.raw30())
        v = validate_layout(spec, [rect(*r) for r in CERT_30M])
        self.assertEqual(v["overall"], "PASS", [r["explanation"] for r in v["results"] if r["result"] == "FAIL"])
        self.assertEqual(v["summary"]["failed"], 0)
        self.assertLessEqual(max(r[1] + r[3] for r in CERT_30M), 30)
        self.assertLessEqual(max(r[2] + r[4] for r in CERT_30M), 16)

    @unittest.expectedFailure
    def test_baseline_heuristic_finds_a_valid_layout_when_one_exists(self):
        # Still an open limitation of the BASELINE (method="heuristic"); the CP-SAT generator resolves the case.
        self.assertEqual(run_pipeline(self.raw30(), method="heuristic")["validation"]["overall"], "PASS")


if __name__ == "__main__":
    unittest.main()
