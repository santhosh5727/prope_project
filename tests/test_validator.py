"""The validator checks given geometry from first principles."""
import ast
import unittest
from pathlib import Path

from pharma_layout import validator
from pharma_layout.validator import validate_layout
from tests.helpers import make_spec, rect, result

# 20 x 10 building, two rooms side by side, exactly tiling the left 10 m.
SPEC = make_spec([("A", 50), ("B", 50)], adjacency=[("A", "B")])
GOOD = [rect("A", 0, 0, 5, 10), rect("B", 5, 0, 5, 10)]


class ValidLayout(unittest.TestCase):
    def test_feasible_layout_passes_everything(self):
        v = validate_layout(SPEC, GOOD)
        self.assertEqual(v["overall"], "PASS", [r for r in v["results"] if r["result"] == "FAIL"])
        self.assertEqual(v["summary"]["failed"], 0)
        # A and B are each 10 m tall and share their full vertical edge
        self.assertIn("10.00 m boundary", result(v, "V-08:ADJ-01")["explanation"])

    def test_every_result_carries_traceability_fields(self):
        for r in validate_layout(SPEC, GOOD)["results"]:
            for key in ("rule_id", "description", "inputs", "result", "explanation"):
                self.assertTrue(r[key] is not None and r[key] != "", (r["rule_id"], key))


class Overlap(unittest.TestCase):
    def test_overlapping_rooms_fail_v05_and_name_both(self):
        v = validate_layout(SPEC, [rect("A", 0, 0, 5, 10), rect("B", 4, 0, 5, 10)])
        r = result(v, "V-05")
        self.assertEqual(r["result"], "FAIL")
        self.assertEqual(r["offenders"], ["A", "B"])
        self.assertIn("overlap by 10.000 m2", r["explanation"])
        self.assertEqual(v["overall"], "FAIL")

    def test_overlap_also_fails_adjacency_with_reason(self):
        v = validate_layout(SPEC, [rect("A", 0, 0, 5, 10), rect("B", 4, 0, 5, 10)])
        self.assertIn("overlap", result(v, "V-08:ADJ-01")["explanation"])
        self.assertEqual(result(v, "V-08:ADJ-01")["result"], "FAIL")

    def test_touching_edges_are_not_overlap(self):
        self.assertEqual(result(validate_layout(SPEC, GOOD), "V-05")["result"], "PASS")


class Boundary(unittest.TestCase):
    def test_room_outside_right_edge(self):
        v = validate_layout(SPEC, [rect("A", 0, 0, 5, 10), rect("B", 17, 0, 5, 10)])
        r = result(v, "V-04")
        self.assertEqual(r["result"], "FAIL")
        self.assertEqual(r["offenders"], ["B"])
        self.assertIn("right edge 2.000 m outside", r["explanation"])

    def test_room_outside_negative_coordinates(self):
        v = validate_layout(SPEC, [rect("A", -1, -2, 5, 10), rect("B", 5, 0, 5, 10)])
        r = result(v, "V-04")
        self.assertEqual(r["result"], "FAIL")
        self.assertIn("left edge 1.000 m", r["explanation"])
        self.assertIn("top edge 2.000 m", r["explanation"])

    def test_room_outside_bottom(self):
        v = validate_layout(SPEC, [rect("A", 0, 3, 5, 10), rect("B", 5, 0, 5, 10)])
        self.assertIn("bottom edge 3.000 m outside", result(v, "V-04")["explanation"])

    def test_room_exactly_on_boundary_is_inside(self):
        spec = make_spec([("A", 200)])
        self.assertEqual(result(validate_layout(spec, [rect("A", 0, 0, 20, 10)]), "V-04")["result"], "PASS")


class TotalAreaAndDimensions(unittest.TestCase):
    def test_impossible_total_area_fails_v02(self):
        spec = make_spec([("A", 150), ("B", 100)])  # 250 > 200
        v = validate_layout(spec, [rect("A", 0, 0, 15, 10), rect("B", 15, 0, 10, 10)])
        r = result(v, "V-02")
        self.assertEqual(r["result"], "FAIL")
        self.assertIn("exceeds building 200.00 m2 by 50.00 m2", r["explanation"])

    def test_non_positive_dimensions_fail_v03(self):
        v = validate_layout(SPEC, [rect("A", 0, 0, 0, 10), rect("B", 5, 0, 5, -10)])
        r = result(v, "V-03")
        self.assertEqual(r["result"], "FAIL")
        self.assertEqual(r["offenders"], ["A", "B"])

    def test_area_deviation_reported_and_tolerance_respected(self):
        # A is 5.2 x 10 = 52 m2 vs 50 required (+4 %) -> fails default 2 % tolerance
        v = validate_layout(SPEC, [rect("A", 0, 0, 5.2, 10), rect("B", 5.2, 0, 5, 10)])
        self.assertEqual(result(v, "V-06")["result"], "FAIL")
        self.assertIn("+4.0 %", result(v, "V-06")["explanation"])
        loose = make_spec([("A", 50), ("B", 50)], area_rel_tol=0.05)
        v2 = validate_layout(loose, [rect("A", 0, 0, 5.2, 10), rect("B", 5.2, 0, 5, 10)])
        self.assertEqual(result(v2, "V-06")["result"], "PASS")

    def test_minimum_dimension(self):
        spec = make_spec([("A", 50, 6.0), ("B", 50)])
        v = validate_layout(spec, GOOD)  # A is 5 x 10: shorter side 5 < 6
        self.assertEqual(result(v, "V-07")["result"], "FAIL")
        self.assertIn("shorter side 5.00 m < minimum 6 m", result(v, "V-07")["explanation"])

    def test_min_dim_not_applicable_when_unspecified(self):
        self.assertEqual(result(validate_layout(SPEC, GOOD), "V-07")["result"], "N/A")


class Adjacency(unittest.TestCase):
    def adj(self, layout, spec=SPEC):
        return result(validate_layout(spec, layout), "V-08:ADJ-01")

    def test_unsatisfied_adjacency_separated_by_gap(self):
        r = self.adj([rect("A", 0, 0, 5, 10), rect("B", 9, 0, 5, 10)])
        self.assertEqual(r["result"], "FAIL")
        self.assertFalse(r["satisfied"])
        self.assertIn("closest approach is 4.00 m", r["explanation"])

    def test_corner_contact_is_not_adjacent(self):
        r = self.adj([rect("A", 0, 0, 5, 5), rect("B", 5, 5, 5, 5)])
        self.assertEqual(r["result"], "FAIL")
        self.assertIn("only at a corner", r["explanation"])

    def test_short_shared_edge_below_minimum_fails(self):
        r = self.adj([rect("A", 0, 0, 5, 10), rect("B", 5, 9.5, 5, 0.5)])  # shares 0.5 m < 1.0 m
        self.assertEqual(r["result"], "FAIL")
        self.assertIn("share only 0.50 m", r["explanation"])

    def test_shared_edge_at_exact_minimum_passes(self):
        self.assertEqual(self.adj([rect("A", 0, 0, 5, 10), rect("B", 5, 9, 5, 1)])["result"], "PASS")

    def test_horizontal_adjacency_passes(self):
        self.assertEqual(self.adj([rect("A", 0, 0, 10, 5), rect("B", 0, 5, 10, 5)])["result"], "PASS")

    def test_adjacency_with_unplaced_room_fails(self):
        r = self.adj([rect("A", 0, 0, 5, 10)])
        self.assertEqual(r["result"], "FAIL")
        self.assertIn("B not placed", r["explanation"])


class Completeness(unittest.TestCase):
    def test_missing_room_fails_v01(self):
        r = result(validate_layout(SPEC, [rect("A", 0, 0, 5, 10)]), "V-01")
        self.assertEqual(r["result"], "FAIL")
        self.assertIn("not placed: B", r["explanation"])

    def test_unknown_and_duplicate_rooms(self):
        v = validate_layout(SPEC, GOOD + [rect("ZZZ", 0, 0, 1, 1), rect("A", 1, 1, 1, 1)])
        e = result(v, "V-01")["explanation"]
        self.assertIn("'ZZZ' is not in the spec", e)
        self.assertIn("A is placed more than once", e)

    def test_non_numeric_values_do_not_crash(self):
        bad = [{"id": "A", "x": "0", "y": 0, "w": 5, "h": 10}, {"id": "B", "x": float("nan"), "y": 0, "w": 5, "h": 10}, "junk", None]
        v = validate_layout(SPEC, bad)
        self.assertEqual(result(v, "V-01")["result"], "FAIL")
        self.assertEqual(v["overall"], "FAIL")

    def test_layout_not_a_list(self):
        self.assertEqual(validate_layout(SPEC, {"A": 1})["overall"], "FAIL")

    def test_empty_layout_fails_without_crashing(self):
        v = validate_layout(SPEC, [])
        self.assertEqual(v["overall"], "FAIL")
        self.assertEqual(result(v, "V-05")["result"], "N/A")


class Independence(unittest.TestCase):
    def test_validator_does_not_import_generator(self):
        tree = ast.parse(Path(validator.__file__).read_text())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add(("." * n.level) + (n.module or ""))
        self.assertFalse([m for m in mods if "generator" in m], mods)

    def test_corrupting_generator_output_is_caught(self):
        from pharma_layout.generator import generate_layout
        from tests.helpers import demo_raw
        from pharma_layout.spec import validate_spec
        spec = validate_spec(demo_raw())
        gen = generate_layout(spec)
        self.assertEqual(gen["status"], "placed")
        self.assertEqual(validate_layout(spec, gen["rooms"])["overall"], "PASS")
        gen["rooms"][0]["x"] += 100  # generator still "says" placed; validator must object
        v = validate_layout(spec, gen["rooms"])
        self.assertEqual(v["overall"], "FAIL")
        self.assertEqual(result(v, "V-04")["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
