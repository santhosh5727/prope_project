"""CP-SAT generator: acceptance tests. Tests that need OR-Tools are skipped (not failed) when it is not installed:
run the whole suite with the project venv (./.venv/bin/python -m unittest discover -s tests -t .) to execute them."""
import ast
import importlib.util
import json
import random
import subprocess
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import pharma_layout
from pharma_layout import cpsat, generator, validator
from pharma_layout.generator import generate_layout
from pharma_layout.pipeline import run_pipeline
from pharma_layout.server import make_server
from pharma_layout.spec import SpecError, validate_spec
from pharma_layout.validator import validate_layout
from tests.helpers import demo_raw, rect, result
from tests.test_audit_regressions import CERT_30M

HAVE_ORTOOLS = importlib.util.find_spec("ortools") is not None
needs_ortools = unittest.skipUnless(HAVE_ORTOOLS, "OR-Tools not installed (pip install -r requirements-cpsat.txt)")
ROOT = Path(pharma_layout.__file__).resolve().parent.parent


def spec_of(rooms, adjacency=(), W=10.0, H=10.0, generator=None, **tol):
    """rooms: (id, area[, min_dim]); adjacency: (a, b) pairs. Returns a validated spec."""
    raw = {"building": {"width_m": W, "height_m": H},
           "rooms": [{"id": r[0], "area_m2": r[1], **({"min_dim_m": r[2]} if len(r) > 2 else {})} for r in rooms],
           "adjacency": [{"id": f"ADJ-{i + 1:02d}", "a": a, "b": b} for i, (a, b) in enumerate(adjacency)]}
    if tol:
        raw["tolerances"] = tol
    raw["generator"] = {"method": "cpsat", **(generator or {})}
    return validate_spec(raw)


def demo_cpsat(width=24, **gen):
    raw = demo_raw(); raw["building"]["width_m"] = width
    raw["generator"] = {"method": "cpsat", **gen}
    return raw


class GeneratorSettings(unittest.TestCase):
    def test_defaults_keep_the_baseline_heuristic(self):
        g = validate_spec(demo_raw())["generator"]
        self.assertEqual((g["method"], g["grid_m"], g["objective"], g["num_workers"], g["seed"]), ("heuristic", 0.1, "feasibility", 1, 1))
        self.assertEqual(g["source"], "assumption")

    def test_bad_generator_settings_are_rejected_with_all_errors(self):
        raw = demo_raw()
        raw["generator"] = {"method": "magic", "grid_m": 0, "objective": 3, "time_limit_s": 1e9, "num_workers": 0, "seed": True, "user_fields": ["x"]}
        with self.assertRaises(SpecError) as cm:
            validate_spec(raw)
        text = "\n".join(cm.exception.errors)
        for key in ("method", "grid_m", "objective", "time_limit_s", "num_workers", "seed", "user_fields"):
            self.assertIn(f"generator.{key}", text)

    def test_generator_not_an_object_or_unhashable_values(self):
        for bad in ([], "x", {"method": ["cpsat"]}, {"source": []}, {"objective": {}}):
            raw = demo_raw(); raw["generator"] = bad
            with self.assertRaises(SpecError):
                validate_spec(raw)

    def test_unknown_method_override_is_a_spec_error(self):
        with self.assertRaises(SpecError):
            run_pipeline(demo_raw(), method="annealing")


class StatusSemantics(unittest.TestCase):
    def test_map_status(self):
        self.assertEqual(cpsat.map_status("OPTIMAL", True), "OPTIMAL")
        self.assertEqual(cpsat.map_status("OPTIMAL", False), "FEASIBLE")   # nothing to optimise: only feasibility is shown
        for raw in ("FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"):
            self.assertEqual(cpsat.map_status(raw, True), raw)
        self.assertEqual(cpsat.map_status("SOMETHING_NEW", True), "MODEL_INVALID")   # never a conclusion

    def test_missing_ortools_is_a_configuration_error_not_a_crash(self):
        with mock.patch.object(cpsat, "_import_ortools", side_effect=ImportError("no module")):
            self.assertFalse(cpsat.capabilities()["cpsat"])
            res = run_pipeline(demo_cpsat())
        g = res["generation"]
        self.assertEqual((g["status"], g["solver"]["status"]), ("error", "MODEL_INVALID"))
        self.assertEqual(res["validation"]["overall"], "FAIL")
        self.assertIn("MODEL_INVALID", res["html"])
        self.assertNotIn("infeasible", " ".join(g["reasons"]).lower())

    def test_generator_module_boundaries(self):
        def imported(path):
            mods = set()
            for n in ast.walk(ast.parse(Path(path).read_text())):
                if isinstance(n, ast.Import): mods |= {a.name for a in n.names}
                elif isinstance(n, ast.ImportFrom): mods.add(("." * n.level) + (n.module or ""))
            return mods
        self.assertFalse([m for m in imported(cpsat.__file__) if "validator" in m])
        self.assertFalse([m for m in imported(generator.__file__) if "validator" in m])
        self.assertFalse([m for m in imported(validator.__file__) if "cpsat" in m or "generator" in m])


class FakeSolver:
    """Stands in for OR-Tools' CpSolver so that every status path can be exercised deterministically."""
    def __init__(self, name):
        self.name, self.wall_time, self.objective_value, self.best_objective_bound = name, 0.5, 0.0, 0.0
    def solve(self, model): return 0
    def status_name(self, code): return self.name
    def value(self, var): raise AssertionError("no solution values exist for this status")


@needs_ortools
class StatusPaths(unittest.TestCase):
    def run_with(self, status):
        with mock.patch.object(cpsat, "_solver", lambda cp_model, cfg: FakeSolver(status)):
            return run_pipeline(demo_cpsat())

    def test_unknown_is_never_an_infeasibility_claim(self):
        res = self.run_with("UNKNOWN")
        g = res["generation"]
        self.assertEqual((g["status"], g["solver"]["status"]), ("unknown", "UNKNOWN"))
        self.assertNotIn(g["status"], ("infeasible", "infeasible_on_grid"))
        self.assertIn("NOT a claim", " ".join(g["reasons"]))
        self.assertIn("UNKNOWN", res["html"])
        self.assertNotIn("the inputs are infeasible", res["html"])
        self.assertNotIn("infeasible for the grid model", res["html"])
        self.assertEqual(res["validation"]["overall"], "FAIL")   # no layout -> not a success either

    def test_infeasible_is_scoped_to_the_grid_model(self):
        res = self.run_with("INFEASIBLE")
        g = res["generation"]
        self.assertEqual((g["status"], g["solver"]["status"]), ("infeasible_on_grid", "INFEASIBLE"))
        self.assertIn("NOT a proof for layouts with off-grid coordinates", " ".join(g["reasons"]))
        self.assertNotIn("the inputs are infeasible", res["html"])   # that wording is reserved for continuous-space proofs

    def test_model_invalid_is_an_error(self):
        g = self.run_with("MODEL_INVALID")["generation"]
        self.assertEqual((g["status"], g["solver"]["status"]), ("error", "MODEL_INVALID"))

    def test_grid_coarser_than_building_is_model_invalid(self):
        spec = spec_of([("A", 0.2)], W=0.5, H=0.5, generator={"grid_m": 1.0})
        g = generate_layout(spec)
        self.assertEqual((g["status"], g["solver"]["status"]), ("error", "MODEL_INVALID"))

    def test_real_time_limit_never_yields_an_infeasibility_claim(self):
        res = run_pipeline(demo_cpsat(30, time_limit_s=0.01, objective="min_area_deviation"))
        g = res["generation"]
        self.assertIn(g["status"], ("placed", "unknown"))
        if g["status"] == "placed":
            self.assertIn(g["solver"]["status"], ("OPTIMAL", "FEASIBLE"))
        else:
            self.assertEqual(g["solver"]["status"], "UNKNOWN")

    def test_failed_validation_is_never_reported_as_success(self):
        bad = {"status": "placed", "reasons": [], "self_report": {"unsatisfied_adjacency": [], "min_dim_violations": []},
               "rooms": [{"id": r["id"], "x": 0.0, "y": 0.0, "w": 2.0, "h": 2.0} for r in demo_raw()["rooms"]],   # all stacked
               "unallocated_area_m2": 0.0, "method": {"name": "cp-sat", "grid_m": 0.1, "objective": "feasibility"},
               "solver": {"status": "OPTIMAL", "raw_status": "OPTIMAL", "elapsed_s": 0.1, "grid_m": 0.1, "objective": "feasibility"}}
        with mock.patch("pharma_layout.pipeline.generate_layout", return_value=bad):
            res = run_pipeline(demo_cpsat())
        self.assertEqual(res["validation"]["overall"], "FAIL")
        self.assertTrue(any("FAILED independent validation" in n for n in res["notes"]), res["notes"])
        self.assertNotIn("encoded checks passed", res["html"])


@needs_ortools
class AcceptanceCases(unittest.TestCase):
    def test_demo_24m_passes_independent_validator(self):
        res = run_pipeline(demo_cpsat(24))
        g, v = res["generation"], res["validation"]
        self.assertEqual(g["status"], "placed")
        self.assertIn(g["solver"]["status"], ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(v["overall"], "PASS", [r["explanation"] for r in v["results"] if r["result"] == "FAIL"])
        self.assertEqual((v["summary"]["passed"], v["summary"]["failed"]), (15, 0))
        self.assertEqual(res["notes"], [])

    def test_known_valid_30m_case_is_found_and_validated(self):
        # A valid layout exists (CERT_30M, see test_audit_regressions); the baseline heuristic misses it.
        self.assertEqual(validate_layout(validate_spec(demo_cpsat(30)), [rect(*r) for r in CERT_30M])["overall"], "PASS")
        res = run_pipeline(demo_cpsat(30))
        v = res["validation"]
        self.assertEqual(res["generation"]["status"], "placed")
        self.assertEqual(v["overall"], "PASS", [r["explanation"] for r in v["results"] if r["result"] == "FAIL"])
        self.assertEqual(run_pipeline(demo_cpsat(30), method="heuristic")["validation"]["overall"], "FAIL")   # same spec, baseline

    def test_deviation_objective_reaches_a_proved_optimum(self):
        spec = spec_of([("A", 40, 4.0), ("B", 30, 3.0), ("C", 20, 3.0)], [("A", "B"), ("B", "C")], W=10, H=12,
                       generator={"objective": "min_area_deviation"})
        g = generate_layout(spec)
        self.assertEqual((g["status"], g["solver"]["status"], g["solver"]["raw_status"]), ("placed", "OPTIMAL", "OPTIMAL"))
        self.assertEqual(g["solver"]["objective_value"], 0)          # every room exactly its required area on the grid
        self.assertEqual(validate_layout(spec, g["rooms"])["overall"], "PASS")

    def test_feasibility_objective_reports_feasible_not_optimal(self):
        g = generate_layout(spec_of([("A", 40, 4.0), ("B", 30, 3.0)], [("A", "B")], W=10, H=12))
        self.assertEqual((g["status"], g["solver"]["status"]), ("placed", "FEASIBLE"))

    def test_deterministic_for_fixed_settings(self):
        spec = spec_of([("A", 40, 4.0), ("B", 30, 3.0), ("C", 20, 3.0)], [("A", "B"), ("B", "C")], W=10, H=12)
        a, b = generate_layout(spec), generate_layout(spec)
        self.assertEqual(a["rooms"], b["rooms"])

    def test_grid_approximations_are_reported(self):
        spec = spec_of([("A", 40, 4.05)], W=10.04, H=12, generator={"grid_m": 0.1})
        g = generate_layout(spec)
        notes = " ".join(g["solver"]["approximations"])
        self.assertIn("building floored", notes)
        self.assertIn("min_dim_m rounded up", notes)


@needs_ortools
class UnsatisfiableAdjacency(unittest.TestCase):
    def test_wall_longer_than_the_building_is_proved_infeasible_without_solving(self):
        raw = demo_cpsat(24); raw["tolerances"]["min_shared_edge_m"] = 50
        res = run_pipeline(raw)
        g = res["generation"]
        self.assertEqual(g["status"], "infeasible")
        self.assertIsNone(g["solver"])                                   # decided by arithmetic, solver never ran
        self.assertIn("continuous space", g["infeasibility_scope"])
        self.assertIn("longer than both building sides", " ".join(g["reasons"]))
        self.assertEqual(res["validation"]["overall"], "FAIL")

    def test_geometrically_impossible_adjacency_is_infeasible_on_the_grid_only(self):
        # Four 25 m2 rooms with both sides >= 5 m fill a 10 x 10 m building as a 2 x 2 block; diagonal rooms touch only
        # at a corner, so "everyone adjacent to everyone" cannot hold.
        ids = "ABCD"
        pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
        spec = spec_of([(i, 25, 5.0) for i in ids], pairs, W=10, H=10)
        self.assertEqual(generator.precheck(spec), [])                   # cheap tests cannot rule it out
        res = run_pipeline({"building": spec["building"], "rooms": spec["rooms"], "adjacency": spec["adjacency"],
                            "generator": {"method": "cpsat"}})
        g = res["generation"]
        self.assertEqual((g["status"], g["solver"]["status"]), ("infeasible_on_grid", "INFEASIBLE"))
        self.assertIn("discretised model only", " ".join(g["reasons"]))
        self.assertEqual(res["validation"]["overall"], "FAIL")
        self.assertIn("infeasible for the grid model only", res["html"])

    def test_a_satisfiable_adjacency_graph_is_still_solved(self):
        spec = spec_of([(i, 25, 5.0) for i in "ABCD"], [("A", "B"), ("B", "C"), ("C", "D")], W=10, H=10)
        g = generate_layout(spec)
        self.assertEqual(g["status"], "placed")
        self.assertEqual(validate_layout(spec, g["rooms"])["overall"], "PASS")


@needs_ortools
class FixTheVariables(unittest.TestCase):
    """Pin every variable to a given layout: the model must accept exactly what the independent validator accepts."""
    SPEC = spec_of([("A", 40, 4.5), ("B", 30, 3.0), ("C", 20, 3.0)], [("A", "B"), ("B", "C")], W=10, H=12)
    VALID = [rect("A", 0, 0, 5, 8), rect("B", 5, 0, 5, 6), rect("C", 5, 6, 5, 4)]

    def verdicts(self, layout, spec=None):
        spec = spec or self.SPEC
        return validate_layout(spec, layout)["overall"], cpsat.check_fixed_layout(spec, layout)["status"]

    def test_known_valid_layout_is_accepted_by_both(self):
        self.assertEqual(self.verdicts(self.VALID), ("PASS", "FEASIBLE"))

    def test_known_invalid_layouts_are_rejected_by_both(self):
        L = self.VALID
        invalid = {
            "overlap": [L[0], rect("B", 4, 0, 5, 6), L[2]],
            "outside building": [L[0], L[1], rect("C", 5, 8, 5, 4)],
            "area outside +-2 % band": [L[0], rect("B", 5, 0, 5, 6.5), L[2]],
            "minimum dimension": [rect("A", 0, 0, 10, 4), rect("B", 0, 4, 5, 6), rect("C", 5, 4, 5, 4)],
            "gap instead of adjacency": [L[0], L[1], rect("C", 5, 7, 5, 4)],
        }
        for name, layout in invalid.items():
            val, mod = self.verdicts(layout)
            self.assertEqual(val, "FAIL", f"validator should reject: {name}")
            self.assertIn(mod, ("INFEASIBLE", "OFF_GRID"), f"model should reject: {name}")
        # these invalid layouts are on the grid, so the model itself (not just "off grid") must reject them
        for name, layout in invalid.items():
            self.assertEqual(cpsat.check_fixed_layout(self.SPEC, layout)["status"], "INFEASIBLE", name)

    def test_corner_only_contact_is_rejected_by_both(self):
        wide = spec_of([("A", 40, 4.5), ("B", 30, 3.0), ("C", 20, 3.0)], [("A", "B"), ("B", "C")], W=15, H=12)
        corner = [rect("A", 0, 0, 5, 8), rect("B", 5, 0, 5, 6), rect("C", 10, 6, 5, 4)]   # C touches B only at the point (10, 6)
        v = validate_layout(wide, corner)
        self.assertEqual([r["result"] for r in v["results"] if r["rule_id"] != "V-08:ADJ-02"].count("FAIL"), 0)   # only B-C fails
        self.assertIn("only at a corner", result(v, "V-08:ADJ-02")["explanation"])
        self.assertEqual(cpsat.check_fixed_layout(wide, corner)["status"], "INFEASIBLE")
        moved = [rect("A", 0, 0, 5, 8), rect("B", 5, 0, 5, 6), rect("C", 10, 5, 5, 4)]   # shares 1 m of wall with B
        self.assertEqual((validate_layout(wide, moved)["overall"], cpsat.check_fixed_layout(wide, moved)["status"]), ("PASS", "FEASIBLE"))

    def test_area_band_is_exactly_plus_minus_tolerance_on_the_grid(self):
        spec = spec_of([("A", 30)], W=20, H=10)    # accepted: 29.4 .. 30.6 m2, i.e. 2940 .. 3060 cells of 0.01 m2
        ok = lambda w, h: cpsat.check_fixed_layout(spec, [rect("A", 0, 0, w, h)])["status"]
        self.assertEqual(ok(10.2, 3.0), "FEASIBLE")      # 30.60 m2 = +2.0 % exactly
        self.assertEqual(ok(9.8, 3.0), "FEASIBLE")       # 29.40 m2 = -2.0 % exactly
        self.assertEqual(ok(10.3, 3.0), "INFEASIBLE")    # 30.90 m2
        self.assertEqual(ok(9.7, 3.0), "INFEASIBLE")     # 29.10 m2
        self.assertEqual(ok(10.2, 3.1), "INFEASIBLE")    # 31.62 m2
        self.assertEqual(ok(10.1, 3.0), "FEASIBLE")      # 30.30 m2
        # the validator agrees at the exact boundary (this is AUD-06 from the model's side)
        for w in (10.2, 9.8):
            self.assertEqual(result(validate_layout(spec, [rect("A", 0, 0, w, 3.0)]), "V-06")["result"], "PASS")

    def test_off_grid_layout_gets_no_opinion_from_the_model(self):
        r = cpsat.check_fixed_layout(self.SPEC, [rect("A", 0, 0, 5.05, 8), rect("B", 5, 0, 5, 6), rect("C", 5, 6, 5, 4)])
        self.assertEqual(r["status"], "OFF_GRID")

    def test_model_and_validator_agree_on_random_layouts(self):
        rng = random.Random(2026)
        agree = pos = neg = 0
        for _ in range(60):
            n = rng.randint(3, 4)
            rooms, adj = [], []
            for i in range(n):
                w, h = rng.randint(4, 12) / 2, rng.randint(4, 12) / 2      # half-metre sizes
                rooms.append((f"R{i}", w * h, rng.choice([None, 2.0, 2.5])))
            for _k in range(rng.randint(0, 3)):
                a, b = sorted(rng.sample(range(n), 2)); adj.append((f"R{a}", f"R{b}"))
            adj = sorted(set(adj))
            spec = spec_of([(r[0], r[1]) if r[2] is None else r for r in rooms], adj, W=8, H=8, generator={"grid_m": 0.5})
            placed = generate_layout(spec)
            layouts = []
            if placed["status"] == "placed":
                layouts.append(placed["rooms"])
                for _k in range(4):                                         # perturb one room: usually breaks something
                    lay = [dict(p) for p in placed["rooms"]]
                    p = rng.choice(lay)
                    if rng.random() < .75:
                        p["x" if rng.random() < .5 else "y"] += rng.choice([-1.0, -0.5, 0.5, 1.0])
                    else:
                        p["w"], p["h"] = p["h"], p["w"]
                    layouts.append(lay)
            for _k in range(3):                                             # fully random layouts
                layouts.append([{"id": r[0], "x": rng.randint(0, 12) / 2, "y": rng.randint(0, 12) / 2,
                                 "w": rng.randint(4, 12) / 2, "h": rng.randint(4, 12) / 2} for r in rooms])
            for lay in layouts:
                val = validate_layout(spec, lay)["overall"]
                mod = cpsat.check_fixed_layout(spec, lay)["status"]
                self.assertEqual(mod == "FEASIBLE", val == "PASS", (val, mod, rooms, adj, lay))
                agree += 1; pos += val == "PASS"; neg += val != "PASS"
        self.assertGreater(pos, 20)      # the comparison is meaningful in both directions
        self.assertGreater(neg, 100)


@needs_ortools
class IntegrationSurfaces(unittest.TestCase):
    def test_cli_runs_cpsat_on_the_demo(self):
        r = subprocess.run([sys.executable, "-m", "pharma_layout", "run", "examples/synthetic_osd_demo.json", "--method", "cpsat"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout[-400:] + r.stderr[-400:])
        self.assertIn("generator: cp-sat | status: placed | solver FEASIBLE", r.stdout)
        self.assertIn("OVERALL: PASS", r.stdout)

    def test_http_api_runs_cpsat_for_the_30m_case(self):
        srv = make_server("127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            caps = json.loads(urllib.request.urlopen(base + "/api/capabilities", timeout=10).read())
            self.assertTrue(caps["cpsat"])
            req = urllib.request.Request(base + "/api/run", data=json.dumps(demo_cpsat(30)).encode(), headers={"Content-Type": "application/json"})
            body = json.loads(urllib.request.urlopen(req, timeout=120).read())
        finally:
            srv.shutdown(); srv.server_close()
        self.assertEqual((body["ok"], body["overall"], body["generation"]["solver"]["status"]), (True, "PASS", "FEASIBLE"))
        self.assertIn("CP-SAT", body["html"])


class CliExitCodes(unittest.TestCase):
    def run_cli(self, text, *args):
        p = ROOT / "tests" / "_cli_tmp_spec.json"
        p.write_text(text)
        try:
            return subprocess.run([sys.executable, "-m", "pharma_layout", "run", str(p), *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
        finally:
            p.unlink()

    def test_malformed_input_exits_2_with_no_traceback(self):
        for name, mut in {"list source": lambda d: d["rooms"][0].__setitem__("source", ["x"]),
                          "huge int": lambda d: d["building"].__setitem__("width_m", 10 ** 400)}.items():
            d = demo_raw(); mut(d)
            r = self.run_cli(json.dumps(d))
            self.assertEqual(r.returncode, 2, (name, r.stderr[-300:]))
            self.assertNotIn("Traceback", r.stderr, name)

    def test_unreadable_json_exits_2(self):
        for text in ("{not json", "[" * 50000 + "]" * 50000):
            r = self.run_cli(text)
            self.assertEqual(r.returncode, 2, r.stderr[-300:])
            self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
