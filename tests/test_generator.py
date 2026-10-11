"""Generator behaviour, judged by the independent validator."""
import random
import unittest

from pharma_layout.generator import generate_layout
from pharma_layout.pipeline import run_pipeline
from pharma_layout.spec import validate_spec
from pharma_layout.validator import validate_layout
from tests.helpers import demo_raw, make_spec, result


class FeasibleCase(unittest.TestCase):
    def setUp(self):
        self.spec = validate_spec(demo_raw())
        self.gen = generate_layout(self.spec)
        self.val = validate_layout(self.spec, self.gen["rooms"])

    def test_demo_layout_is_valid_per_independent_validator(self):
        self.assertEqual(self.gen["status"], "placed")
        self.assertEqual(self.val["overall"], "PASS", [r["explanation"] for r in self.val["results"] if r["result"] == "FAIL"])
        self.assertEqual(self.val["summary"]["failed"], 0)

    def test_all_eight_adjacencies_met_and_self_report_agrees(self):
        adj = [r for r in self.val["results"] if r["rule_id"].startswith("V-08:")]
        self.assertEqual((len(adj), sum(r["result"] == "PASS" for r in adj)), (8, 8))
        self.assertEqual(self.gen["self_report"], {"unsatisfied_adjacency": [], "min_dim_violations": []})

    def test_every_room_gets_exactly_its_required_area(self):
        req = {r["id"]: r["area_m2"] for r in self.spec["rooms"]}
        for p in self.gen["rooms"]:
            self.assertAlmostEqual(p["w"] * p["h"], req[p["id"]], places=6)

    def test_unallocated_area_is_reported(self):
        self.assertAlmostEqual(self.gen["unallocated_area_m2"], 384 - 296, places=6)

    def test_deterministic(self):
        self.assertEqual(generate_layout(self.spec), generate_layout(validate_spec(demo_raw())))


class ImpossibleTotalArea(unittest.TestCase):
    def test_infeasible_with_reason_and_no_placements(self):
        raw = demo_raw(); raw["building"]["width_m"] = 10  # 10 x 16 = 160 m2 < 296 m2
        res = run_pipeline(raw)
        self.assertEqual(res["generation"]["status"], "infeasible")
        self.assertEqual(res["generation"]["rooms"], [])
        self.assertIn("exceeds building area 160.00 m2", res["generation"]["reasons"][0])
        v = res["validation"]
        self.assertEqual(v["overall"], "FAIL")
        self.assertEqual(result(v, "V-02")["result"], "FAIL")
        self.assertEqual(result(v, "V-01")["result"], "FAIL")
        self.assertIn("the inputs are infeasible", res["html"])  # the report banner explains why

    def test_room_min_dim_larger_than_building(self):
        spec = make_spec([("A", 50, 15.0)], W=20, H=10)
        g = generate_layout(spec)
        self.assertEqual(g["status"], "infeasible")
        self.assertIn("exceeds the shorter building side", g["reasons"][0])

    def test_room_area_smaller_than_min_dim_squared(self):
        spec = make_spec([("A", 4, 3.0), ("B", 20)])
        g = generate_layout(spec)
        self.assertEqual(g["status"], "infeasible")
        self.assertIn("cannot have both sides", " ".join(g["reasons"]))


class UnsatisfiedRequirementsAreReported(unittest.TestCase):
    def test_unsatisfiable_adjacency_is_not_hidden(self):
        raw = demo_raw(); raw["tolerances"]["min_shared_edge_m"] = 50  # longer than the building: no pair can qualify
        res = run_pipeline(raw)
        gen_unsat = set(res["generation"]["self_report"]["unsatisfied_adjacency"])
        val_unsat = {r["rule_id"].split(":")[1] for r in res["validation"]["results"]
                     if r["rule_id"].startswith("V-08:") and r["result"] == "FAIL"}
        self.assertEqual(len(gen_unsat), 8)
        self.assertEqual(gen_unsat, val_unsat)
        self.assertEqual(res["validation"]["overall"], "FAIL")
        self.assertEqual(res["notes"], [])  # generator and validator agree
        self.assertIn("NOT met", res["html"])

    def test_unavoidable_min_dim_violation_is_reported(self):
        # 98 + 2 = 100 m2 in 10 x 10: any row split makes B at most 0.2 m thick in one axis
        spec = make_spec([("A", 98, 5.0), ("B", 2, 1.4)], W=10, H=10)
        g = generate_layout(spec)
        self.assertEqual(g["status"], "placed")
        self.assertIn("B", g["self_report"]["min_dim_violations"])
        v = validate_layout(spec, g["rooms"])
        self.assertEqual(result(v, "V-07")["result"], "FAIL")
        self.assertEqual(v["overall"], "FAIL")


class KnownLimitation(unittest.TestCase):
    def test_wider_building_is_not_always_easier_and_failure_is_reported_honestly(self):
        """The row heuristic is not monotone in building size. At 30 x 16 m no contiguous row
        partition of the chain order avoids a minimum-dimension violation for WASTE. The failure must
        be visible (validator FAIL, named room) and the generator's self-report must agree.
        If the heuristic is ever improved so this passes, update this test and the README."""
        raw = demo_raw(); raw["building"]["width_m"] = 30
        res = run_pipeline(raw)
        self.assertFalse(res["generation"]["method"]["search_truncated"])
        self.assertEqual(res["generation"]["self_report"]["min_dim_violations"], ["WASTE"])
        v = res["validation"]
        self.assertEqual((v["overall"], result(v, "V-07")["result"]), ("FAIL", "FAIL"))
        self.assertEqual(result(v, "V-07")["offenders"], ["WASTE"])
        self.assertEqual(res["notes"], [])
        # widths either side of 30 do pass, so this is a heuristic limit, not an infeasible spec
        for w in (24, 28):
            raw["building"]["width_m"] = w
            self.assertEqual(run_pipeline(raw)["validation"]["overall"], "PASS", w)


class Misc(unittest.TestCase):
    def test_single_room(self):
        spec = make_spec([("A", 200)])
        g = generate_layout(spec)
        self.assertEqual(validate_layout(spec, g["rooms"])["overall"], "PASS")

    def test_rooms_without_adjacency_requirements(self):
        spec = make_spec([("A", 60), ("B", 40), ("C", 30)])
        g = generate_layout(spec)
        self.assertEqual(validate_layout(spec, g["rooms"])["overall"], "PASS")

    def test_random_specs_geometry_always_valid_and_generator_agrees_with_validator(self):
        rng = random.Random(12345)
        for _ in range(40):
            n = rng.randint(2, 9)
            W, H = rng.choice([20, 24, 30]), rng.choice([10, 14, 16])
            areas = [rng.randint(8, 40) for _ in range(n)]
            scale = min(1.0, 0.9 * W * H / sum(areas))
            rooms = [(f"R{i}", max(4.0, round(a * scale, 2))) for i, a in enumerate(areas)]
            if sum(a for _, a in rooms) > W * H:
                continue
            pairs = {tuple(sorted(rng.sample(range(n), 2))) for _ in range(rng.randint(0, n))}
            adj = [(f"R{a}", f"R{b}") for a, b in pairs]
            spec = make_spec(rooms, adj, W=W, H=H)
            res = run_pipeline({"building": spec["building"], "tolerances": spec["tolerances"],
                                "rooms": spec["rooms"], "adjacency": spec["adjacency"]})
            v = res["validation"]
            for rid in ("V-01", "V-02", "V-03", "V-04", "V-05", "V-06"):
                self.assertEqual(result(v, rid)["result"], "PASS", (rid, rooms, adj))
            self.assertEqual(res["notes"], [], (rooms, adj))  # generator self-report == validator


if __name__ == "__main__":
    unittest.main()
