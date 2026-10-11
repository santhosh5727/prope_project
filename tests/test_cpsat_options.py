"""Phase-3 tests: the opt-in CP-SAT model options and compactness objectives must be SOUND.

A model option is allowed to change how fast the solver searches, never which layouts count as correct:
  * tight_domains / linear_adjacency / cumulative_cuts must accept exactly the layouts the base model (and the independent
    validator) accepts - tested by pinning every variable to a layout (``check_fixed_layout``);
  * mirror_symmetry / twin_symmetry only remove symmetric copies: feasibility must be unchanged and the layout returned must
    still pass the validator;
  * a hint only changes the starting point;
  * compactness objectives keep every constraint (the validator passes) and reach hand-computed optima.
Expensive speed measurements are NOT here: see benchmarks/experiment.py.
"""
import importlib.util
import random
import unittest

from pharma_layout import cpsat
from pharma_layout.generator import generate_layout
from pharma_layout.pipeline import run_pipeline
from pharma_layout.spec import GENERATOR_MODEL_OPTIONS, SpecError, validate_spec
from pharma_layout.validator import validate_layout
from tests.helpers import demo_raw, rect
from tests.test_cpsat import demo_cpsat, needs_ortools, spec_of

PURE_ENCODING = ("tight_domains", "linear_adjacency", "cumulative_cuts")


class OptionSettings(unittest.TestCase):
    def test_options_and_objectives_are_validated(self):
        ok = demo_raw(); ok["generator"] = {"model_options": ["linear_adjacency", "tight_domains", "tight_domains"], "objective": "min_bbox_area"}
        g = validate_spec(ok)["generator"]
        self.assertEqual(g["model_options"], ["linear_adjacency", "tight_domains"])      # sorted, de-duplicated
        self.assertEqual(g["objective"], "min_bbox_area")
        for bad in ("tight_domains", ["nope"], [1], [["x"]], {"a": 1}):
            raw = demo_raw(); raw["generator"] = {"model_options": bad}
            with self.assertRaises(SpecError, msg=repr(bad)) as cm:
                validate_spec(raw)
            self.assertIn("generator.model_options", "\n".join(cm.exception.errors))

    def test_default_is_the_base_model(self):
        self.assertEqual(validate_spec(demo_raw())["generator"]["model_options"], [])
        self.assertEqual(set(GENERATOR_MODEL_OPTIONS), set(cpsat.MODEL_OPTIONS))


def _random_cases(seed, count):
    """(spec, layouts): small specs on a 0.5 m grid plus on-grid layouts that are valid or broken in some way."""
    rng = random.Random(seed)
    out = []
    while len(out) < count:
        n = rng.randint(3, 4)
        rooms = []
        for i in range(n):
            w, h = rng.randint(4, 12) / 2, rng.randint(4, 12) / 2
            rooms.append((f"R{i}", w * h, 2.0) if rng.random() < 0.5 else (f"R{i}", w * h))
        adj = sorted({tuple(sorted(rng.sample(range(n), 2))) for _ in range(rng.randint(0, 3))})
        spec = spec_of(rooms, [(f"R{a}", f"R{b}") for a, b in adj], W=8, H=8, generator={"grid_m": 0.5})
        base = generate_layout(spec)
        if base["status"] != "placed":
            continue
        layouts = [base["rooms"]]
        for _ in range(5):
            lay = [dict(p) for p in base["rooms"]]
            p = rng.choice(lay)
            k = rng.choice(["x", "y", "w", "h"])
            p[k] = max(0.5, p[k] + rng.choice([-1.0, -0.5, 0.5, 1.0]))
            layouts.append(lay)
        out.append((spec, layouts))
    return out


@needs_ortools
class PureEncodingOptionsAcceptExactlyTheSameLayouts(unittest.TestCase):
    cases = None

    @classmethod
    def setUpClass(cls):
        cls.cases = _random_cases(11, 25)

    def test_each_option_and_all_together_agree_with_base_model_and_validator(self):
        combos = [(o,) for o in PURE_ENCODING] + [PURE_ENCODING]
        accepted = rejected = 0
        for spec, layouts in self.cases:
            for lay in layouts:
                base = cpsat.check_fixed_layout(spec, lay)["status"]
                val = validate_layout(spec, lay)["overall"]
                if base != "OFF_GRID":
                    self.assertEqual(base == "FEASIBLE", val == "PASS", (base, val, lay))
                for combo in combos:
                    s2 = validate_spec({**{k: v for k, v in _raw(spec).items()}, "generator": {**_gen(spec), "model_options": list(combo)}})
                    self.assertEqual(cpsat.check_fixed_layout(s2, lay)["status"], base, (combo, lay))
                accepted += base == "FEASIBLE"; rejected += base == "INFEASIBLE"
        self.assertGreater(accepted, 20); self.assertGreater(rejected, 20)    # the comparison is not vacuous

    def test_every_adjacency_failure_mode_is_still_rejected(self):
        spec = spec_of([("A", 40, 4.5), ("B", 30, 3.0)], [("A", "B")], W=15, H=14, generator={"model_options": ["linear_adjacency"]})
        good = [rect("A", 0, 0, 5, 8), rect("B", 5, 0, 5, 6)]
        self.assertEqual(cpsat.check_fixed_layout(spec, good)["status"], "FEASIBLE")
        for name, lay in {"gap": [rect("A", 0, 0, 5, 8), rect("B", 5.1, 0, 5, 6)],
                          "corner only": [rect("A", 0, 0, 5, 8), rect("B", 5, 8, 5, 6)],
                          "shared wall 0.9 m": [rect("A", 0, 0, 5, 8), rect("B", 5, 7.1, 5, 6)],
                          "overlap": [rect("A", 0, 0, 5, 8), rect("B", 4.9, 0, 5, 6)]}.items():
            self.assertEqual(cpsat.check_fixed_layout(spec, lay)["status"], "INFEASIBLE", name)
        self.assertEqual(cpsat.check_fixed_layout(spec, [rect("A", 0, 0, 5, 8), rect("B", 5, 7, 5, 6)])["status"], "FEASIBLE")   # exactly 1.0 m


@needs_ortools
class ThinRoomAdjacency(unittest.TestCase):
    """A sliver room touching a wall along less than the minimum shared edge must be rejected whichever side it is on."""
    def test_sliver_neighbour_is_rejected_by_validator_and_every_encoding(self):
        for pair in (("A", "S"), ("S", "A")):
            for opts in ([], ["linear_adjacency"], sorted(PURE_ENCODING)):
                spec = spec_of([("A", 40, 4.5), ("S", 3.0)], [pair], W=15, H=14, generator={"grid_m": 0.5, "model_options": opts})
                lay = [rect("A", 0, 0, 5, 8), rect("S", 5, 2, 6, 0.5)]          # S touches A over 0.5 m only
                self.assertEqual(validate_layout(spec, lay)["overall"], "FAIL")
                self.assertEqual(cpsat.check_fixed_layout(spec, lay)["status"], "INFEASIBLE", (pair, opts))
                ok = [rect("A", 0, 0, 5, 8), rect("S", 5, 2, 0.5, 6)]            # same room turned: 6 m of shared wall
                self.assertEqual(validate_layout(spec, ok)["overall"], "PASS")
                self.assertEqual(cpsat.check_fixed_layout(spec, ok)["status"], "FEASIBLE", (pair, opts))


def _raw(spec):
    """Rebuild a raw dict from a validated spec (enough for validate_spec to accept it again)."""
    return {"building": {"width_m": spec["building"]["width_m"], "height_m": spec["building"]["height_m"]},
            "rooms": [{"id": r["id"], "area_m2": r["area_m2"], **({"min_dim_m": r["min_dim_m"]} if r["min_dim_m"] is not None else {})} for r in spec["rooms"]],
            "adjacency": [{"id": a["id"], "a": a["a"], "b": a["b"]} for a in spec["adjacency"]]}


def _gen(spec):
    g = spec["generator"]
    return {k: g[k] for k in ("method", "grid_m", "objective", "time_limit_s", "num_workers", "seed", "deterministic_time_limit_s")}


@needs_ortools
class SymmetryBreakingIsSound(unittest.TestCase):
    OPTS = (["mirror_symmetry"], ["twin_symmetry"], ["mirror_symmetry", "twin_symmetry"], ["core_first"], sorted(cpsat.MODEL_OPTIONS))

    def solve(self, rooms, adj, W, H, opts, **kw):
        spec = spec_of(rooms, adj, W=W, H=H, generator={"grid_m": 0.5, "time_limit_s": 30, "model_options": opts, **kw})
        res = run_pipeline(_raw_with_gen(spec))
        return spec, res

    def test_premise_the_mirror_image_of_a_valid_layout_is_valid(self):
        spec = spec_of([("A", 40, 4.5), ("B", 30, 3.0), ("C", 20, 3.0)], [("A", "B"), ("B", "C")], W=10, H=12)
        lay = [rect("A", 0, 0, 5, 8), rect("B", 5, 0, 5, 6), rect("C", 5, 6, 5, 4)]
        mx = [rect(p["id"], 10 - p["x"] - p["w"], p["y"], p["w"], p["h"]) for p in lay]
        my = [rect(p["id"], p["x"], 12 - p["y"] - p["h"], p["w"], p["h"]) for p in lay]
        for variant in (lay, mx, my):
            self.assertEqual(validate_layout(spec, variant)["overall"], "PASS")

    def test_feasibility_is_unchanged_on_random_small_specs(self):
        rng = random.Random(5)
        seen = {"FEASIBLE": 0, "INFEASIBLE": 0}
        for t in range(40):
            n = rng.randint(4, 5)
            twin = rng.random() < 0.5
            rooms = [(f"R{i}", 6.0 if twin and i >= 2 else rng.randint(5, 9) * 1.0, 2.0) for i in range(n)]
            k = n - 1 if rng.random() < 0.5 else n          # the last room has no adjacency requirement in half of the specs (core_first!)
            adj = sorted({tuple(sorted(rng.sample(range(k), 2))) for _ in range(rng.randint(5, 10))})
            adj = [(f"R{a}", f"R{b}") for a, b in adj]
            W, H = rng.choice([(6, 5), (6, 6), (7, 6)])
            _, base = self.solve(rooms, adj, W, H, [])
            bstat = base["generation"]["solver"]["status"] if base["generation"].get("solver") else base["generation"]["status"]
            if bstat == "infeasible":          # decided by the arithmetic pre-check before any model exists: nothing to compare
                continue
            self.assertIn(bstat, ("FEASIBLE", "INFEASIBLE"), f"case {t} not decided by the base model: {bstat}")
            seen[bstat] += 1
            for opts in self.OPTS:
                spec, res = self.solve(rooms, adj, W, H, opts)
                g = res["generation"]
                self.assertEqual(g["solver"]["status"] if g.get("solver") else g["status"], bstat, (t, opts))
                if bstat == "FEASIBLE":
                    self.assertEqual(res["validation"]["overall"], "PASS", (t, opts))
        self.assertGreaterEqual(min(seen.values()), 3, seen)       # both outcomes were exercised

    def test_mirror_anchor_sits_in_the_lower_left_quadrant_and_twins_are_ordered(self):
        rooms = [("HUB", 12.0, 2.0), ("T1", 9.0, 2.0), ("T2", 9.0, 2.0), ("T3", 9.0, 2.0), ("L", 6.0, 2.0)]
        adj = [("HUB", "L")]
        spec, res = self.solve(rooms, adj, 9, 9, ["mirror_symmetry", "twin_symmetry"])
        self.assertEqual(res["validation"]["overall"], "PASS")
        p = {r["id"]: r for r in res["generation"]["rooms"]}
        self.assertLessEqual(2 * p["HUB"]["x"] + p["HUB"]["w"], 9 + 1e-9)
        self.assertLessEqual(2 * p["HUB"]["y"] + p["HUB"]["h"], 9 + 1e-9)
        self.assertLessEqual(p["T1"]["x"], p["T2"]["x"]); self.assertLessEqual(p["T2"]["x"], p["T3"]["x"])

    def test_twin_groups_need_identical_area_and_min_dim_and_no_adjacency(self):
        def extra_constraints(rooms, adj, opts):
            spec = spec_of(rooms, adj, W=12, H=12, generator={"grid_m": 0.5, "model_options": opts})
            return len(cpsat.build_model(spec)[1].proto.constraints)
        n = lambda rooms, adj=(): extra_constraints(rooms, adj, ["twin_symmetry"]) - extra_constraints(rooms, adj, [])
        hub = [("H", 12.0, 2.0), ("L", 6.0, 2.0)]
        self.assertEqual(n(hub + [("T1", 9.0, 2.0), ("T2", 9.0, 2.0)], [("H", "L")]), 1)                     # one ordering
        self.assertEqual(n(hub + [("T1", 9.0, 2.0), ("T2", 9.0, 2.0), ("T3", 9.0, 2.0)], [("H", "L")]), 2)     # a chain of three
        self.assertEqual(n(hub + [("T1", 9.0, 2.0), ("T2", 9.0, 3.0)], [("H", "L")]), 0)                     # different min_dim
        self.assertEqual(n(hub + [("T1", 9.0, 2.0), ("T2", 9.0)], [("H", "L")]), 0)                          # one has no min_dim
        self.assertEqual(n(hub + [("T1", 9.0, 2.0), ("T2", 8.0, 2.0)], [("H", "L")]), 0)                     # different area
        self.assertEqual(n(hub + [("T1", 9.0, 2.0), ("T2", 9.0, 2.0)], [("H", "T1"), ("H", "L")]), 0)         # T1 has an adjacency

    def test_fixed_layout_check_ignores_symmetry_options(self):
        spec = spec_of([("A", 40, 4.5), ("B", 30, 3.0), ("C", 20, 3.0)], [("A", "B"), ("B", "C")], W=10, H=12,
                       generator={"model_options": ["mirror_symmetry", "twin_symmetry"]})
        far_right = [rect("A", 5, 4, 5, 8), rect("B", 0, 4, 5, 6), rect("C", 0, 0, 5, 4)]   # anchor B is NOT in the lower-left quadrant
        self.assertEqual(validate_layout(spec, far_right)["overall"], "PASS")
        self.assertEqual(cpsat.check_fixed_layout(spec, far_right)["status"], "FEASIBLE")


def _raw_with_gen(spec):
    r = _raw(spec); r["generator"] = _gen(spec); r["generator"]["model_options"] = list(spec["generator"]["model_options"])
    return r


@needs_ortools
class HeuristicHint(unittest.TestCase):
    def test_hint_gives_a_validator_confirmed_layout_and_is_reported(self):
        res = run_pipeline(demo_cpsat(24, model_options=["heuristic_hint"]))
        self.assertEqual(res["validation"]["overall"], "PASS")
        sol = res["generation"]["solver"]
        self.assertEqual((sol["model_options"], sol["hint_rooms"]), (["heuristic_hint"], 14))

    def test_hint_from_a_failing_heuristic_does_not_prevent_a_valid_layout(self):
        res = run_pipeline(demo_cpsat(30, model_options=["heuristic_hint"]))       # the heuristic alone FAILS at 30 m (AUD-07)
        self.assertEqual(res["validation"]["overall"], "PASS")

    def test_hint_never_turns_an_infeasible_model_feasible(self):
        spec = spec_of([(i, 25, 5.0) for i in "ABCD"], [(a, b) for k, a in enumerate("ABCD") for b in "ABCD"[k + 1:]], W=10, H=10,
                       generator={"model_options": ["heuristic_hint"]})
        res = run_pipeline(_raw_with_gen(spec))
        self.assertEqual((res["generation"]["status"], res["generation"]["solver"]["status"]), ("infeasible_on_grid", "INFEASIBLE"))


@needs_ortools
class CoreFirst(unittest.TestCase):
    K4 = [(a, b) for k, a in enumerate("ABCD") for b in "ABCD"[k + 1:]]

    def spec(self, opts, rooms, adj, W=10, H=10):
        return _raw_with_gen(spec_of(rooms, adj, W=W, H=H, generator={"model_options": opts, "grid_m": 0.5}))

    def test_infeasible_core_proves_the_whole_spec_infeasible_on_the_grid_and_says_how(self):
        rooms = [(i, 25, 5.0) for i in "ABCD"] + [("X", 4.0), ("Y", 4.0)]            # K4 core + two rooms with no requirement
        res = run_pipeline(self.spec(["core_first"], rooms, self.K4, W=14, H=14))
        g = res["generation"]
        self.assertEqual((g["status"], g["solver"]["status"]), ("infeasible_on_grid", "INFEASIBLE"))
        self.assertEqual(g["solver"]["core"]["status"], "INFEASIBLE")
        self.assertEqual(g["solver"]["core"]["rooms"], 4)
        self.assertIn("relaxation", " ".join(g["reasons"]))
        self.assertIn("NOT a proof for layouts with off-grid coordinates", " ".join(g["reasons"]))
        plain = run_pipeline(self.spec([], rooms, self.K4, W=14, H=14))["generation"]        # same verdict without the shortcut
        self.assertEqual(plain["solver"]["status"], "INFEASIBLE")

    def test_feasible_core_hands_a_hint_to_the_full_model(self):
        rooms = [("A", 40, 4.5), ("B", 30, 3.0), ("C", 20, 3.0), ("X", 9.0), ("Y", 9.0)]
        res = run_pipeline(self.spec(["core_first"], rooms, [("A", "B"), ("B", "C")], W=14, H=12))
        sol = res["generation"]["solver"]
        self.assertEqual(sol["core"]["status"], "FEASIBLE"); self.assertEqual(sol["core"]["rooms"], 3)
        self.assertGreaterEqual(sol["hint_rooms"], 3)
        self.assertEqual(res["validation"]["overall"], "PASS")

    def test_no_core_when_every_room_has_an_adjacency_or_there_is_none(self):
        for adj, rooms in (([("A", "B")], [("A", 20), ("B", 20)]), ([], [("A", 20), ("B", 20)])):
            res = run_pipeline(self.spec(["core_first"], rooms, adj))
            self.assertIsNone(res["generation"]["solver"]["core"])

    def test_unknown_relaxation_proves_nothing(self):
        from unittest import mock
        from tests.test_cpsat import FakeSolver
        rooms = [("A", 40, 4.5), ("B", 30, 3.0), ("X", 9.0)]
        with mock.patch.object(cpsat, "_solver", lambda cp_model, cfg: FakeSolver("UNKNOWN")):
            res = run_pipeline(self.spec(["core_first"], rooms, [("A", "B")], W=14, H=12))
        g = res["generation"]
        self.assertEqual((g["status"], g["solver"]["status"]), ("unknown", "UNKNOWN"))     # not "infeasible"
        self.assertEqual(g["solver"]["core"]["status"], "UNKNOWN")


@needs_ortools
class Phase3Regressions(unittest.TestCase):
    """Defects confirmed by experiments on 2026-10-11; each test failed before the fix."""

    def test_both_hint_sources_together_are_not_MODEL_INVALID(self):
        # found by the all-options differential test: the heuristic hint and the core hint named the same variables and
        # OR-Tools rejects a variable hinted twice -> the call came back MODEL_INVALID although the spec is feasible.
        rooms = [("A", 40, 4.5), ("B", 30, 3.0), ("C", 20, 3.0), ("X", 9.0)]
        res = run_pipeline(_raw_with_gen(spec_of(rooms, [("A", "B"), ("B", "C")], W=14, H=12,
                                                 generator={"model_options": ["core_first", "heuristic_hint"], "grid_m": 0.5})))
        self.assertEqual(res["generation"]["solver"]["status"], "FEASIBLE")
        self.assertEqual(res["validation"]["overall"], "PASS")

    def test_time_limit_covers_the_heuristic_hint(self):
        # E1: with heuristic_hint a 20 s limit gave 22 s of wall time because the hint's heuristic ran outside the limit.
        import time
        from unittest import mock
        from tests.test_cpsat import FakeSolver
        seen = []
        real = cpsat.generate_heuristic

        def slow_heuristic(spec):
            time.sleep(0.4); return real(spec)
        def capture(cp_model, cfg):
            seen.append(cfg["time_limit_s"]); return FakeSolver("UNKNOWN")
        raw = demo_cpsat(24, model_options=["heuristic_hint"], time_limit_s=5.0)
        with mock.patch.object(cpsat, "generate_heuristic", slow_heuristic), mock.patch.object(cpsat, "_solver", capture):
            run_pipeline(raw)
        self.assertEqual(len(seen), 1)
        self.assertLess(seen[0], 5.0 - 0.35)

    def test_unknown_message_does_not_recommend_a_coarser_grid(self):
        # E3: on all four benchmark UNKNOWN cases a 0.5 m or 0.25 m grid was infeasible at once (the +-2 % area band has no
        # integer point), so "try a coarser grid" was misleading advice.
        from unittest import mock
        from tests.test_cpsat import FakeSolver
        with mock.patch.object(cpsat, "_solver", lambda cp_model, cfg: FakeSolver("UNKNOWN")):
            msg = " ".join(run_pipeline(demo_cpsat())["generation"]["reasons"])
        self.assertIn("another seed", msg)
        self.assertNotIn("a coarser grid or", msg)
        self.assertIn("NOT a claim of infeasibility", msg)

    def test_coarse_grid_with_tight_area_tolerance_is_infeasible_on_grid_not_unknown(self):
        # benchmark case 15 (random n=12, areas with one decimal): no 0.5 m grid rectangle has an area inside the +-2 % band of some room
        import json
        from pathlib import Path
        spec15 = json.loads(next((Path(__file__).resolve().parent.parent / "benchmarks" / "specs").glob("15_*.json")).read_text())
        spec15["generator"] = {"method": "cpsat", "grid_m": 0.5}
        g = run_pipeline(spec15)["generation"]
        self.assertEqual(g["status"], "infeasible_on_grid")
        self.assertIn("NOT a proof for layouts with off-grid coordinates", " ".join(g["reasons"]))


@needs_ortools
class DeterministicTimeLimit(unittest.TestCase):
    def test_setting_is_validated(self):
        for ok in (None, 1, 0.5, 100000):
            raw = demo_raw(); raw["generator"] = {"deterministic_time_limit_s": ok}
            self.assertEqual(validate_spec(raw)["generator"]["deterministic_time_limit_s"], None if ok is None else float(ok))
        for bad in (0, -1, True, "1", 1e9, float("nan"), [1]):
            raw = demo_raw(); raw["generator"] = {"deterministic_time_limit_s": bad}
            with self.assertRaises(SpecError, msg=repr(bad)):
                validate_spec(raw)
        self.assertIsNone(validate_spec(demo_raw())["generator"]["deterministic_time_limit_s"])      # off by default

    def test_a_wall_clock_cutoff_is_not_reproducible_but_a_work_based_cutoff_is(self):
        # E7: benchmark case 12 (min_bbox_area) with a 0.7 s wall-clock limit gave 6 different layouts in 6 identical runs on one
        # machine; with a work-based limit the 6 runs gave one layout. Only the second claim is asserted here (the first is a
        # property of the machine's timing, shown in benchmarks/runs/e7_d5_*.json).
        import json
        from pathlib import Path
        raw = json.loads(next((Path(__file__).resolve().parent.parent / "benchmarks" / "specs").glob("12_*.json")).read_text())
        raw["generator"] = {"method": "cpsat", "objective": "min_bbox_area", "time_limit_s": 60.0, "deterministic_time_limit_s": 1.0}
        outs = []
        for _ in range(3):
            res = run_pipeline(json.loads(json.dumps(raw)))
            g = res["generation"]
            outs.append((g["solver"]["status"], json.dumps(g["rooms"]), g["solver"]["deterministic_time_limit_s"]))
        self.assertEqual(len(set(outs)), 1)
        self.assertEqual(outs[0][2], 1.0)
        self.assertEqual(outs[0][0], "FEASIBLE")          # a real layout, not three identical empty results


@needs_ortools
class ReportShowsTheSearchSetup(unittest.TestCase):
    def test_options_relaxation_and_work_limit_are_visible_in_the_report(self):
        rooms = [(i, 25, 5.0) for i in "ABCD"] + [("X", 4.0)]
        raw = _raw_with_gen(spec_of(rooms, [(a, b) for k, a in enumerate("ABCD") for b in "ABCD"[k + 1:]], W=14, H=14,
                                    generator={"model_options": ["core_first"], "grid_m": 0.5, "deterministic_time_limit_s": 50}))
        html = run_pipeline(raw)["html"]
        for needle in ("model_options", "core_first", "relaxation on 4 rooms", "deterministic_time_limit_s"):
            self.assertIn(needle, html)


class BenchmarkScriptHygiene(unittest.TestCase):
    def test_importing_compare_generators_does_not_run_the_benchmark(self):
        # it used to call main() at import time: importing it (to reuse cases()) ran minutes of solving and OVERWROTE results.json
        import ast
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "benchmarks" / "compare_generators.py"
        tree = ast.parse(src.read_text())
        bare = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "main"]
        self.assertEqual(bare, [])
        guards = [n for n in tree.body if isinstance(n, ast.If) and "__name__" in ast.dump(n.test)]
        self.assertEqual(len(guards), 1)


@needs_ortools
class CompactnessObjectives(unittest.TestCase):
    def run_single(self, objective, min_dim=None):
        room = ("A", 36.0) if min_dim is None else ("A", 36.0, min_dim)
        spec = spec_of([room], [], W=10, H=10, generator={"objective": objective})
        return run_pipeline(_raw_with_gen(spec))

    def test_bbox_area_hand_computed_optimum(self):
        res = self.run_single("min_bbox_area")
        sol = res["generation"]["solver"]
        # smallest accepted area is 35.28 m2 = 3528 cells of 0.01 m2 (e.g. 6.3 x 5.6)
        self.assertEqual((sol["status"], sol["raw_status"], sol["objective_value"]), ("OPTIMAL", "OPTIMAL", 3528.0))
        self.assertEqual(res["validation"]["overall"], "PASS")

    def test_bbox_perimeter_hand_computed_optimum(self):
        res = self.run_single("min_bbox_perimeter")
        sol = res["generation"]["solver"]
        # w + h = 119 tenths is the smallest sum whose product reaches 3528 (59 x 60 = 3540; 59 x 59 = 3481 is too small)
        self.assertEqual((sol["status"], sol["objective_value"]), ("OPTIMAL", 119.0))
        self.assertEqual(res["validation"]["overall"], "PASS")

    def test_perimeter_objective_has_a_usable_lower_bound(self):
        # E6: the bound reported for min_bbox_perimeter was 80 against a solution of 346 (the LP did not know the box must hold
        # the rooms). Wb * Hb >= total minimum area gives Wb + Hb >= 341 for the 24 x 16 demo.
        res = run_pipeline(demo_cpsat(24, objective="min_bbox_perimeter", time_limit_s=3.0))
        sol = res["generation"]["solver"]
        self.assertIn(sol["status"], ("FEASIBLE", "OPTIMAL"))
        self.assertGreaterEqual(sol["best_objective_bound"], 341.0)
        self.assertLessEqual(sol["best_objective_bound"], sol["objective_value"])
        self.assertEqual(res["validation"]["overall"], "PASS")

    def test_min_dim_is_respected_by_the_compactness_objective(self):
        res = self.run_single("min_bbox_area", min_dim=6.0)
        self.assertEqual(res["generation"]["solver"]["objective_value"], 3600.0)     # 6.0 x 6.0, not the thinner 5.6 x 6.3
        self.assertEqual(res["validation"]["overall"], "PASS")

    def test_compactness_never_trades_away_adjacency_or_boundary(self):
        for objective in ("min_bbox_perimeter", "min_bbox_area"):
            spec = spec_of([("A", 40, 4.5), ("B", 30, 3.0), ("C", 20, 3.0)], [("A", "B"), ("B", "C")], W=14, H=12,
                           generator={"objective": objective, "grid_m": 0.5})
            res = run_pipeline(_raw_with_gen(spec))
            self.assertEqual(res["generation"]["solver"]["status"], "OPTIMAL", objective)
            self.assertEqual(res["validation"]["overall"], "PASS", objective)
            bw = max(r["x"] + r["w"] for r in res["generation"]["rooms"]); bh = max(r["y"] + r["h"] for r in res["generation"]["rooms"])
            self.assertGreaterEqual(bw * bh, 90 * 0.98 - 1e-9)       # the box cannot be smaller than the rooms it holds

    def test_status_semantics_with_a_compactness_objective(self):
        self.assertEqual(cpsat.map_status("OPTIMAL", True), "OPTIMAL")
        res = run_pipeline(demo_cpsat(24, objective="min_bbox_area", time_limit_s=0.05, grid_m=0.1))
        g = res["generation"]
        self.assertIn(g["solver"]["status"], ("FEASIBLE", "UNKNOWN", "OPTIMAL"))
        if g["solver"]["status"] == "UNKNOWN":
            self.assertEqual(g["status"], "unknown")        # a timeout is never turned into an infeasibility claim


if __name__ == "__main__":
    unittest.main()
