"""Invalid or missing input values must be rejected with useful messages."""
import copy
import unittest

from pharma_layout.spec import MAX_ROOMS, SpecError, validate_spec
from tests.helpers import demo_raw


class SpecValidation(unittest.TestCase):
    def errors(self, raw):
        with self.assertRaises(SpecError) as cm:
            validate_spec(raw)
        return cm.exception.errors

    def assert_has(self, errors, *needles):
        text = "\n".join(errors)
        for n in needles:
            self.assertIn(n, text)

    def test_demo_spec_is_valid_and_normalised(self):
        spec = validate_spec(demo_raw())
        self.assertEqual(len(spec["rooms"]), 14)
        self.assertEqual(spec["tolerances"]["area_rel_tol"], 0.02)

    def test_defaults_filled_when_tolerances_omitted(self):
        raw = demo_raw(); del raw["tolerances"]
        t = validate_spec(raw)["tolerances"]
        self.assertEqual((t["area_rel_tol"], t["min_shared_edge_m"], t["source"]), (0.02, 1.0, "assumption"))

    def test_not_an_object(self):
        self.assert_has(self.errors([]), "must be a JSON object")
        self.assert_has(self.errors(None), "must be a JSON object")

    def test_missing_building(self):
        raw = demo_raw(); del raw["building"]
        self.assert_has(self.errors(raw), "building: missing")

    def test_missing_building_height(self):
        raw = demo_raw(); del raw["building"]["height_m"]
        self.assert_has(self.errors(raw), "building.height_m: missing")

    def test_bad_building_dimensions(self):
        for bad in (0, -5, "24", None, float("nan"), float("inf"), True):
            raw = demo_raw(); raw["building"]["width_m"] = bad
            self.assert_has(self.errors(raw), "building.width_m: must be a positive finite number")

    def test_bad_room_areas(self):
        for bad in (0, -1, "30", None, float("nan"), False):
            raw = demo_raw(); raw["rooms"][3]["area_m2"] = bad
            self.assert_has(self.errors(raw), "DISP", "area_m2: must be a positive finite number")

    def test_missing_room_area(self):
        raw = demo_raw(); del raw["rooms"][0]["area_m2"]
        self.assert_has(self.errors(raw), "MAL_IN", "area_m2: missing")

    def test_bad_min_dim(self):
        raw = demo_raw(); raw["rooms"][0]["min_dim_m"] = -2
        self.assert_has(self.errors(raw), "min_dim_m")

    def test_duplicate_room_id(self):
        raw = demo_raw(); raw["rooms"][1]["id"] = "MAL_IN"
        self.assert_has(self.errors(raw), "duplicate room id 'MAL_IN'")

    def test_empty_or_non_list_rooms(self):
        raw = demo_raw(); raw["rooms"] = []
        self.assert_has(self.errors(raw), "rooms: must be a non-empty list")
        raw["rooms"] = "x"
        self.assert_has(self.errors(raw), "rooms: must be a non-empty list")

    def test_too_many_rooms(self):
        raw = demo_raw()
        raw["rooms"] = [{"id": f"R{i}", "name": "r", "area_m2": 1} for i in range(MAX_ROOMS + 1)]
        raw["adjacency"] = []
        self.assert_has(self.errors(raw), "at most")

    def test_adjacency_unknown_room(self):
        raw = demo_raw(); raw["adjacency"][0]["b"] = "NOPE"
        self.assert_has(self.errors(raw), "ADJ-01", "unknown room id 'NOPE'")

    def test_adjacency_self_and_duplicate_pair(self):
        raw = demo_raw(); raw["adjacency"][0]["b"] = raw["adjacency"][0]["a"]
        self.assert_has(self.errors(raw), "adjacent to itself")
        raw = demo_raw(); raw["adjacency"].append({"id": "ADJ-99", "a": "STG_IN", "b": "MAL_IN"})
        self.assert_has(self.errors(raw), "duplicate requirement for pair")

    def test_bad_tolerances(self):
        raw = demo_raw(); raw["tolerances"]["area_rel_tol"] = 1.5
        self.assert_has(self.errors(raw), "tolerances.area_rel_tol")
        raw = demo_raw(); raw["tolerances"]["min_shared_edge_m"] = -1
        self.assert_has(self.errors(raw), "tolerances.min_shared_edge_m")

    def test_tolerance_user_fields_validated(self):
        raw = demo_raw(); raw["tolerances"]["user_fields"] = ["min_shared_edge_m"]
        self.assertEqual(validate_spec(raw)["tolerances"]["user_fields"], ["min_shared_edge_m"])
        for bad in (["nonsense"], "min_shared_edge_m", [1]):
            raw = demo_raw(); raw["tolerances"]["user_fields"] = bad
            self.assert_has(self.errors(raw), "tolerances.user_fields")

    def test_bad_source_tag(self):
        raw = demo_raw(); raw["rooms"][0]["source"] = "official_standard"
        self.assert_has(self.errors(raw), "source: must be one of")

    def test_all_problems_reported_together(self):
        raw = demo_raw()
        raw["building"]["width_m"] = -1
        raw["rooms"][0]["area_m2"] = 0
        raw["adjacency"][0]["a"] = "GHOST"
        self.assertGreaterEqual(len(self.errors(raw)), 3)

    def test_input_not_mutated(self):
        raw = demo_raw(); before = copy.deepcopy(raw)
        validate_spec(raw)
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()
