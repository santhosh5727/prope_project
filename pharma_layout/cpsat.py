"""CP-SAT layout generator (optional dependency: OR-Tools, see requirements-cpsat.txt).

What this module is: a second *generator* behind ``generator.generate_layout``. It proposes a layout; it never
judges one. ``validator.py`` remains the only judge and this module deliberately does not import it. A candidate
that fails validation is reported as a failure by the pipeline, whatever the solver status says.

MODEL (integer grid, ``spec["generator"]["grid_m"]`` = g metres; every coordinate and size is an integer count of g)
  variables   per room i: x_i, y_i (position), w_i, h_i (size); end_x = x + w, end_y = y + h
  boundary    0 <= x, 0 <= y, end_x <= W_u, end_y <= H_u         with W_u = floor(W / g), H_u = floor(H / g)
  overlap     AddNoOverlap2D over the x- and y-intervals           (interiors disjoint; touching is allowed)
  area        (w, h, area, dev) must be a row of an enumerated table: every integer pair with
                  ceil(A (1 - tol) / g^2) <= w*h <= floor(A (1 + tol) / g^2)     <- the exact accepted band
              and w, h >= ceil(min_dim / g).  dev = |w*h - round(A / g^2)|.
  total area  sum(area_i) <= W_u * H_u                              (redundant cut; helps the solver prove area limits)
  adjacency   for each required pair (a, b): at least one of 4 literals
                  "b right of a":  end_x(a) == x(b)  and  min(end_y) - max(y) >= L_u     (and the 3 mirror cases)
              with L_u = ceil(min_shared_edge / g): touching along a wall of at least L, never corner-only.
  objective   "feasibility": none  |  "min_area_deviation": minimise sum(dev_i)  |  compactness, over the constraints above
              (never replacing them): "min_bbox_perimeter" minimises Wb + Hb, "min_bbox_area" minimises Wb * Hb, where
              Wb >= every end_x and Hb >= every end_y (bounding box anchored at the building origin; at an optimum
              the layout touches x = 0 and y = 0, since shifting it there would shrink the box).

OPTIONAL MODEL VARIANTS (``generator.model_options``; default none). Each is meant to change the SEARCH, not the set of
layouts the model accepts; tests/test_cpsat_options.py checks that on the validator's accept/reject decisions, and
benchmarks/experiment.py measures the effect on speed:
  tight_domains     exact bounds for w, h, x, y and the end variables taken from the enumerated (w, h) table; the unused
                    ``dev`` column is dropped unless the objective is min_area_deviation
  linear_adjacency  "overlap along the wall >= L" written as four linear inequalities (every end - every start >= L)
                    instead of min/max auxiliary variables; exactly equivalent
  cumulative_cuts   redundant cumulative constraints (x-sweep: sum of heights <= H_u; y-sweep: sum of widths <= W_u)
  mirror_symmetry   a layout and its mirror images (x -> W_u - x - w, y -> H_u - y - h) are both solutions: require the centre
                    of the highest-degree room to lie in the lower-left quadrant. Sound for any rectangular building
  twin_symmetry     interchangeable rooms (same area and min_dim, no adjacency requirement, not the mirror-anchor room) are
                    ordered by x. Sound: swapping two such rooms maps a solution to a solution
  heuristic_hint    the baseline heuristic's rows are given to the solver as a solution HINT (snapped to the grid, repaired by
                    the solver). A hint never narrows the model; it only changes where the search starts
  core_first        first solve a RELAXATION that keeps only the rooms named in an adjacency requirement (at most
                    CORE_TIME_SHARE of the time limit). Removing rooms can only make the model easier, so if the relaxation is
                    INFEASIBLE the full model is INFEASIBLE too (still "on the grid"): a sound proof, reported with its scope. If
                    the relaxation has a layout it is handed to the full model as a hint. UNKNOWN proves nothing and the full
                    model runs with the remaining time

TIME: ``time_limit_s`` bounds the whole call (pre-check, model building, any hint or relaxation, solving).

APPROXIMATIONS the grid introduces (all of them make the model STRICTER than the validator, never looser, so an
accepted model solution is a candidate the validator can confirm, but a valid off-grid layout can be missed):
  * coordinates and sizes are multiples of g, so off-grid layouts are not representable;
  * the building is floored to a whole number of g in each direction;
  * minimum dimension and minimum shared edge are rounded UP to a multiple of g;
  * the area band is exact for grid sizes (area is w*h in units of g^2); it is not widened or narrowed.
  Spec numbers are converted with exact decimal arithmetic (``Fraction(repr(x))``), not binary floats.

STATUS SEMANTICS (``solver.status``; ``solver.raw_status`` keeps OR-Tools' own name)
  OPTIMAL        proved optimal for the stated objective, within the discretised model
  FEASIBLE       a candidate was found; optimality not proved. Also used for objective "feasibility", where there is
                 nothing to optimise (OR-Tools reports OPTIMAL there; we do not repeat that as an achievement)
  INFEASIBLE     no solution exists for the DISCRETISED model. Not a proof for off-grid layouts. Generation status
                 "infeasible_on_grid" (an arithmetic pre-check in continuous space gives the stronger "infeasible")
  UNKNOWN        no layout and no proof (e.g. time limit). NEVER reported as infeasible. Generation status "unknown"
  MODEL_INVALID  configuration or modelling error (including OR-Tools missing). Generation status "error"

DETERMINISM: default ``num_workers = 1`` with a fixed ``random_seed`` gives a deterministic search for a given
OR-Tools version and platform. Reaching the wall-clock limit is the one path that depends on machine speed.
"""
from __future__ import annotations

import math
import time
from fractions import Fraction

from .generator import generate_heuristic, infeasible_result, precheck

MAX_TABLE_ROWS = 400_000     # total (w, h) rows over all rooms; protects memory/time for very fine grids
MODEL_OPTIONS = ("tight_domains", "linear_adjacency", "cumulative_cuts", "mirror_symmetry", "twin_symmetry", "heuristic_hint", "core_first")
CORE_TIME_SHARE = 0.3        # core_first: at most this share of time_limit_s is spent on the relaxation


class ModelError(Exception):
    """Configuration or modelling problem -> solver status MODEL_INVALID."""


class EmptyDomain(Exception):
    """A room has no (w, h) on the grid satisfying area band, min dimension and building size: infeasible on the grid."""


def _import_ortools():
    from ortools.sat.python import cp_model
    import ortools
    return cp_model, ortools.__version__


def capabilities() -> dict:
    try:
        _, ver = _import_ortools()
        return {"cpsat": True, "ortools_version": ver, "reason": None}
    except Exception as e:  # noqa: BLE001
        return {"cpsat": False, "ortools_version": None,
                "reason": f"OR-Tools is not available ({type(e).__name__}). Install it in a project venv: pip install -r requirements-cpsat.txt"}


def _q(x) -> Fraction:
    """Exact decimal reading of a spec number (0.1 -> 1/10, not the binary double)."""
    return Fraction(repr(x))


def map_status(raw: str, has_objective: bool) -> str:
    """OR-Tools status name -> this project's status. Anything unrecognised is MODEL_INVALID, never a conclusion."""
    if raw == "OPTIMAL":
        return "OPTIMAL" if has_objective else "FEASIBLE"
    if raw in ("FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"):
        return raw
    return "MODEL_INVALID"


# --------------------------------------------------------------------------- model construction
def build_model(spec: dict, fixed: dict | None = None, with_objective: bool = True, hint_layout: dict | None = None):
    """Return (cp_model, model, vars, info). ``fixed`` maps room id -> (x, y, w, h) in grid units and pins the
    variables (used to test the encoding against the validator); ``hint_layout`` has the same shape but is only a search
    hint. Raises ModelError / EmptyDomain."""
    cp_model, version = _import_ortools()
    cfg = spec["generator"]
    g = _q(cfg["grid_m"])
    W_u = math.floor(_q(spec["building"]["width_m"]) / g)
    H_u = math.floor(_q(spec["building"]["height_m"]) / g)
    if W_u < 1 or H_u < 1:
        raise ModelError(f"grid {cfg['grid_m']:g} m is coarser than the building ({spec['building']['width_m']:g} x {spec['building']['height_m']:g} m)")
    notes = []
    if _q(spec["building"]["width_m"]) != W_u * g or _q(spec["building"]["height_m"]) != H_u * g:
        notes.append(f"building floored to {float(W_u * g):g} x {float(H_u * g):g} m on the {cfg['grid_m']:g} m grid")
    tol = _q(spec["tolerances"]["area_rel_tol"])
    L_u = max(1, math.ceil(_q(spec["tolerances"]["min_shared_edge_m"]) / g))
    if _q(spec["tolerances"]["min_shared_edge_m"]) != L_u * g:
        notes.append(f"min_shared_edge_m rounded up to {float(L_u * g):g} m")

    options = set(cfg.get("model_options", ()))
    if not options <= set(MODEL_OPTIONS):
        raise ModelError(f"unknown model option(s): {sorted(options - set(MODEL_OPTIONS))}")
    if fixed is not None:                     # symmetry breaking would reject mirrored layouts; a hint is pointless when pinned
        options -= {"mirror_symmetry", "twin_symmetry", "heuristic_hint"}
    objective = cfg["objective"]
    tight = "tight_domains" in options
    need_dev = objective == "min_area_deviation" or not tight

    m = cp_model.CpModel()
    X, Y, Wd, Hd, Ar, Dv, XE, YE, IX, IY = {}, {}, {}, {}, {}, {}, {}, {}, [], []
    a_lo_sum = 0
    table_rows = 0
    for r in spec["rooms"]:
        i = r["id"]
        area = _q(r["area_m2"])
        a_lo = math.ceil(area * (1 - tol) / (g * g))
        a_hi = math.floor(area * (1 + tol) / (g * g))
        if r["min_dim_m"] is None:
            md = 1
        else:
            md = max(1, math.ceil(_q(r["min_dim_m"]) / g))
            if _q(r["min_dim_m"]) != md * g:
                notes.append(f"{i}: min_dim_m rounded up to {float(md * g):g} m")
        target = round(area / (g * g))
        rows = []
        for w in range(md, W_u + 1):
            h_lo, h_hi = max(md, -(-a_lo // w)), min(H_u, a_hi // w)
            for h in range(h_lo, h_hi + 1):
                rows.append((w, h, w * h, abs(w * h - target)) if need_dev else (w, h, w * h))
        if not rows:
            raise EmptyDomain(f"room {i}: no integer (w, h) on the {cfg['grid_m']:g} m grid has area within the accepted band "
                              f"[{float(a_lo * g * g):.4g}, {float(a_hi * g * g):.4g}] m2 and both sides >= {float(md * g):g} m inside the building")
        table_rows += len(rows)
        if table_rows > MAX_TABLE_ROWS:
            raise ModelError(f"grid {cfg['grid_m']:g} m is too fine for this spec ({table_rows}+ table rows; limit {MAX_TABLE_ROWS})")
        a_lo_sum += a_lo
        if tight:
            wlo, whi = min(row[0] for row in rows), max(row[0] for row in rows)
            hlo, hhi = min(row[1] for row in rows), max(row[1] for row in rows)
        else:
            wlo, whi, hlo, hhi = md, W_u, md, H_u
        X[i], Y[i] = m.new_int_var(0, W_u - (wlo if tight else 0), f"x_{i}"), m.new_int_var(0, H_u - (hlo if tight else 0), f"y_{i}")
        Wd[i], Hd[i] = m.new_int_var(wlo, whi, f"w_{i}"), m.new_int_var(hlo, hhi, f"h_{i}")
        Ar[i] = m.new_int_var(a_lo, a_hi, f"a_{i}")
        if need_dev:
            Dv[i] = m.new_int_var(0, max(row[3] for row in rows), f"d_{i}")
            m.add_allowed_assignments([Wd[i], Hd[i], Ar[i], Dv[i]], rows)
        else:
            m.add_allowed_assignments([Wd[i], Hd[i], Ar[i]], rows)
        xe, ye = m.new_int_var(wlo if tight else 0, W_u, f"xe_{i}"), m.new_int_var(hlo if tight else 0, H_u, f"ye_{i}")   # end <= building = boundary rule
        XE[i], YE[i] = xe, ye
        m.add(xe == X[i] + Wd[i]); m.add(ye == Y[i] + Hd[i])
        IX.append(m.new_interval_var(X[i], Wd[i], xe, f"ix_{i}"))
        IY.append(m.new_interval_var(Y[i], Hd[i], ye, f"iy_{i}"))
    m.add_no_overlap_2d(IX, IY)
    m.add(sum(Ar.values()) <= W_u * H_u)
    if "cumulative_cuts" in options:
        ids = [r["id"] for r in spec["rooms"]]
        m.add_cumulative(IX, [Hd[i] for i in ids], H_u)
        m.add_cumulative(IY, [Wd[i] for i in ids], W_u)

    span = max(W_u, H_u)
    for a in spec["adjacency"]:
        p, q = a["a"], a["b"]
        lits = []
        for axis in ("x", "y"):
            P, S = (X, Wd) if axis == "x" else (Y, Hd)    # contact is normal to this axis
            O, T = (Y, Hd) if axis == "x" else (X, Wd)    # shared length is measured along the other axis
            if "linear_adjacency" not in options:
                hi, lo = m.new_int_var(0, span, ""), m.new_int_var(0, span, "")
                m.add_min_equality(hi, [O[p] + T[p], O[q] + T[q]])
                m.add_max_equality(lo, [O[p], O[q]])
            for first, second in ((p, q), (q, p)):
                lit = m.new_bool_var("")
                m.add(P[first] + S[first] == P[second]).only_enforce_if(lit)
                if "linear_adjacency" in options:      # min(ends) - max(starts) >= L  <=>  every end - every start >= L
                    for e, st in ((p, p), (p, q), (q, p), (q, q)):
                        m.add(O[e] + T[e] - O[st] >= L_u).only_enforce_if(lit)
                else:
                    m.add(hi - lo >= L_u).only_enforce_if(lit)
                lits.append(lit)
        m.add_bool_or(lits)

    anchor = None
    if "mirror_symmetry" in options or "twin_symmetry" in options:
        deg = {r["id"]: 0 for r in spec["rooms"]}
        for a in spec["adjacency"]:
            deg[a["a"]] += 1; deg[a["b"]] += 1
        anchor = max(spec["rooms"], key=lambda r: deg[r["id"]])["id"]          # first of the highest-degree rooms
        if "mirror_symmetry" in options:
            m.add(2 * X[anchor] + Wd[anchor] <= W_u)
            m.add(2 * Y[anchor] + Hd[anchor] <= H_u)
        if "twin_symmetry" in options:
            groups = {}
            for r in spec["rooms"]:
                if r["id"] != anchor and deg[r["id"]] == 0:
                    groups.setdefault((r["area_m2"], r["min_dim_m"]), []).append(r["id"])
            for ids in groups.values():
                for a_, b_ in zip(ids, ids[1:]):
                    m.add(X[a_] <= X[b_])
    hint_rooms = 0
    clip = lambda v, hi: max(0, min(hi, int(v)))

    hints = {}      # variable -> value; a later source overrides an earlier one (OR-Tools rejects a variable hinted twice)

    def hint(i, x, y, w, h):
        for var, val, hi in ((X[i], x, W_u), (Y[i], y, H_u), (Wd[i], w, W_u), (Hd[i], h, H_u), (XE[i], x + w, W_u), (YE[i], y + h, H_u)):
            hints[var.index] = (var, clip(val, hi))

    if "heuristic_hint" in options:
        h = generate_heuristic(spec)
        if h.get("status") == "placed":
            gf = float(g)
            for p in h["rooms"]:
                hint(p["id"], *(round(p[k] / gf) for k in ("x", "y", "w", "h")))
            hint_rooms = len(h["rooms"])
    if hint_layout and fixed is None:
        for i, t in hint_layout.items():
            if i in X:
                hint(i, *t)
        hint_rooms = max(hint_rooms, len([i for i in hint_layout if i in X]))
    for var, val in hints.values():
        m.add_hint(var, val)

    if fixed is not None:
        for i, (x, y, w, h) in fixed.items():
            m.add(X[i] == x); m.add(Y[i] == y); m.add(Wd[i] == w); m.add(Hd[i] == h)
    has_objective = with_objective and objective != "feasibility"
    if has_objective:
        if objective == "min_area_deviation":
            m.minimize(sum(Dv.values()))
        else:
            Wb, Hb = m.new_int_var(0, W_u, "bbox_w"), m.new_int_var(0, H_u, "bbox_h")
            for i in XE:
                m.add(Wb >= XE[i]); m.add(Hb >= YE[i])
            if objective == "min_bbox_perimeter":
                # The box holds the rooms, so Wb * Hb >= S (their minimum total area). Hence Wb + Hb >= k, the least k with
                # floor(k / 2) * ceil(k / 2) >= S. Redundant (changes no solution) but without it the LP bound was ~4x too weak.
                k = 2 * math.isqrt(a_lo_sum)
                while (k * k) // 4 < a_lo_sum:
                    k += 1
                m.add(Wb + Hb >= k)
                m.minimize(Wb + Hb)
            else:
                Ab = m.new_int_var(a_lo_sum, W_u * H_u, "bbox_area")          # the box must hold the rooms' minimum total area
                m.add_multiplication_equality(Ab, [Wb, Hb])
                m.minimize(Ab)
    info = {"grid": g, "W_u": W_u, "H_u": H_u, "notes": notes, "has_objective": has_objective,
            "table_rows": table_rows, "ortools_version": version, "options": sorted(options), "hint_rooms": hint_rooms,
            "symmetry_anchor": anchor}
    return cp_model, m, {"X": X, "Y": Y, "W": Wd, "H": Hd}, info


def _solver(cp_model, cfg):
    s = cp_model.CpSolver()
    if {"heuristic_hint", "core_first"} & set(cfg.get("model_options", ())):
        s.parameters.repair_hint = True          # a hint that violates a constraint is repaired, never trusted
    s.parameters.max_time_in_seconds = float(cfg["time_limit_s"])
    if cfg.get("deterministic_time_limit_s") is not None:
        s.parameters.max_deterministic_time = float(cfg["deterministic_time_limit_s"])   # work-based: same cut-off on any machine speed
    s.parameters.num_workers = int(cfg["num_workers"])
    s.parameters.random_seed = int(cfg["seed"])
    return s


def _remaining(cfg, t0) -> float:
    """What is left of ``time_limit_s`` after the work since t0 (floor 0.01 s, the smallest limit the settings accept)."""
    return max(0.01, float(cfg["time_limit_s"]) - (time.perf_counter() - t0))


def _core_spec(spec):
    """The spec restricted to rooms named in an adjacency requirement, or None when that is not a proper subset."""
    used = {x for a in spec["adjacency"] for x in (a["a"], a["b"])}
    rooms = [r for r in spec["rooms"] if r["id"] in used]
    if not spec["adjacency"] or len(rooms) == len(spec["rooms"]):
        return None
    gen = {**spec["generator"], "objective": "feasibility",
           "model_options": [o for o in spec["generator"]["model_options"] if o not in ("core_first", "heuristic_hint")]}
    return {**spec, "rooms": rooms, "generator": gen}


def _solve_core(spec, t0):
    """core_first. Returns (info or None, hint layout or None, proven_infeasible). Never raises: a failed relaxation is just skipped."""
    cs = _core_spec(spec)
    if cs is None:
        return None, None, False
    t1 = time.perf_counter()
    try:
        cp_model, m, v, _ = build_model(cs, with_objective=False)
        s = _solver(cp_model, {**cs["generator"], "time_limit_s": max(0.01, min(CORE_TIME_SHARE * spec["generator"]["time_limit_s"], _remaining(spec["generator"], t0)))})
        status = map_status(s.status_name(s.solve(m)), False)
    except EmptyDomain:
        return {"rooms": len(cs["rooms"]), "status": "INFEASIBLE", "seconds": round(time.perf_counter() - t1, 3)}, None, True
    except Exception:  # noqa: BLE001 - the relaxation is an optimisation only
        return {"rooms": len(cs["rooms"]), "status": "SKIPPED", "seconds": round(time.perf_counter() - t1, 3)}, None, False
    info = {"rooms": len(cs["rooms"]), "status": status, "seconds": round(time.perf_counter() - t1, 3)}
    layout = None
    if status in ("FEASIBLE", "OPTIMAL"):
        layout = {i: tuple(s.value(v[k][i]) for k in ("X", "Y", "W", "H")) for i in v["X"]}
    return info, layout, status == "INFEASIBLE"


def _err(spec, status, reasons, t0, solver_status="MODEL_INVALID", raw=None, extra=None):
    cfg = spec["generator"]
    sol = {"status": solver_status, "raw_status": raw, "elapsed_s": round(time.perf_counter() - t0, 3),
           "grid_m": cfg["grid_m"], "scope": "discretised model"}
    sol.update(extra or {})
    return {"status": status, "rooms": [], "reasons": reasons,
            "self_report": {"unsatisfied_adjacency": None, "min_dim_violations": None},
            "unallocated_area_m2": None, "method": {"name": "cp-sat", "grid_m": cfg["grid_m"]}, "solver": sol}


def generate_cpsat(spec: dict) -> dict:
    """CP-SAT generator. ``spec`` must already be validated by ``spec.validate_spec``. See module docstring."""
    t0 = time.perf_counter()
    cfg = spec["generator"]
    reasons = precheck(spec)     # sound in continuous space -> strongest possible "infeasible"
    if reasons:
        res = infeasible_result(reasons, "cp-sat")
        res["method"]["grid_m"] = cfg["grid_m"]
        return res
    core, core_layout = None, None
    if "core_first" in cfg.get("model_options", ()):
        core, core_layout, proven = _solve_core(spec, t0)
        if proven:
            res = _err(spec, "infeasible_on_grid", [_grid_msg(cfg, f"proved on a relaxation that keeps only the {core['rooms']} of "
                                                                    f"{len(spec['rooms'])} rooms named in an adjacency requirement; removing rooms can only make the model "
                                                                    f"easier, so the full model is infeasible too")],
                       t0, solver_status="INFEASIBLE", raw="INFEASIBLE",
                       extra={"model_options": sorted(cfg["model_options"]), "core": core, "time_limit_s": cfg["time_limit_s"],
                              "num_workers": cfg["num_workers"], "seed": cfg["seed"], "objective": cfg["objective"]})
            res["method"] = {"name": "cp-sat", "grid_m": cfg["grid_m"], "objective": cfg["objective"]}
            return res
    try:
        cp_model, m, v, info = build_model(spec, hint_layout=core_layout)
    except ImportError as e:
        return _err(spec, "error", [capabilities()["reason"]], t0)
    except ModelError as e:
        return _err(spec, "error", [f"MODEL_INVALID: {e}"], t0)
    except EmptyDomain as e:
        # Enumeration proved the room cannot exist on the grid, hence the model is infeasible without solving.
        return _err(spec, "infeasible_on_grid", [_grid_msg(cfg, str(e))], t0, solver_status="INFEASIBLE", raw="EMPTY_DOMAIN")
    except Exception as e:  # noqa: BLE001
        return _err(spec, "error", [f"MODEL_INVALID: internal modelling error {type(e).__name__}: {str(e)[:200]}"], t0)

    err = m.validate()
    if err:
        return _err(spec, "error", [f"MODEL_INVALID: OR-Tools rejected the model: {err[:200]}"], t0, raw="MODEL_INVALID")
    try:
        s = _solver(cp_model, {**cfg, "time_limit_s": _remaining(cfg, t0)})
        raw = s.status_name(s.solve(m))
    except Exception as e:  # noqa: BLE001
        return _err(spec, "error", [f"MODEL_INVALID: solver failure {type(e).__name__}: {str(e)[:200]}"], t0)
    status = map_status(raw, info["has_objective"])
    elapsed = round(time.perf_counter() - t0, 3)
    solver = {"status": status, "raw_status": raw, "elapsed_s": elapsed, "solve_s": round(s.wall_time, 3),
              "objective": cfg["objective"], "grid_m": cfg["grid_m"], "scope": "discretised model",
              "ortools_version": info["ortools_version"], "num_workers": cfg["num_workers"], "seed": cfg["seed"],
              "time_limit_s": cfg["time_limit_s"], "deterministic_time_limit_s": cfg.get("deterministic_time_limit_s"),
              "deterministic_time": round(float(getattr(getattr(s, "response_proto", None), "deterministic_time", 0.0)), 6), "table_rows": info["table_rows"], "approximations": info["notes"],
              "model_options": info["options"], "hint_rooms": info["hint_rooms"], "core": core,
              "objective_value": None, "best_objective_bound": None}
    if info["has_objective"] and status in ("OPTIMAL", "FEASIBLE"):
        solver["objective_value"] = s.objective_value
        solver["best_objective_bound"] = s.best_objective_bound
    method = {"name": "cp-sat", "grid_m": cfg["grid_m"], "objective": cfg["objective"]}

    if status in ("OPTIMAL", "FEASIBLE"):
        g = info["grid"]
        W, H = float(spec["building"]["width_m"]), float(spec["building"]["height_m"])
        rooms = [{"id": r["id"], **{k: float(s.value(var[r["id"]]) * g) for k, var in
                                    (("x", v["X"]), ("y", v["Y"]), ("w", v["W"]), ("h", v["H"]))}} for r in spec["rooms"]]
        used = sum(p["w"] * p["h"] for p in rooms)
        return {"status": "placed", "rooms": rooms, "reasons": [],
                # advisory only: what the model enforces. The validator re-checks everything from scratch.
                "self_report": {"unsatisfied_adjacency": [], "min_dim_violations": []},
                "unallocated_area_m2": round(W * H - used, 6), "method": method, "solver": solver}
    if status == "INFEASIBLE":
        res = _err(spec, "infeasible_on_grid", [_grid_msg(cfg)], t0, solver_status="INFEASIBLE", raw=raw, extra=solver)
    elif status == "UNKNOWN":
        res = _err(spec, "unknown", [
            f"CP-SAT stopped after {elapsed:.1f} s without finding a layout or proving infeasibility (UNKNOWN). "
            "This is NOT a claim of infeasibility: try a longer time limit, another seed or the heuristic. "
            "(A coarser grid is rarely a remedy: with a tight area tolerance it can make the model infeasible at once.)"],
            t0, solver_status="UNKNOWN", raw=raw, extra=solver)
    else:
        res = _err(spec, "error", [f"MODEL_INVALID: OR-Tools returned status {raw}"], t0, raw=raw, extra=solver)
    res["method"] = method
    return res


def _grid_msg(cfg, detail: str | None = None) -> str:
    base = (f"No layout exists on the {cfg['grid_m']:g} m grid under the stated constraints (CP-SAT model INFEASIBLE). "
            "This is a statement about the discretised model only, NOT a proof for layouts with off-grid coordinates.")
    return base + (f" Detail: {detail}" if detail else "")


# --------------------------------------------------------------------------- encoding test hook
def check_fixed_layout(spec: dict, layout_rooms: list[dict]) -> dict:
    """Pin every variable of the model to ``layout_rooms`` and ask the solver whether that layout is feasible.

    Used to test the ENCODING against the independent validator (a correct encoding accepts exactly the layouts
    the validator passes, for grid-aligned layouts). Returns {"status": mapped status, "raw_status", "problems"}.
    status OFF_GRID means the layout cannot be expressed on the grid, so the model has no opinion."""
    cfg = spec["generator"]
    g = _q(cfg["grid_m"])
    fixed, problems = {}, []
    by_id = {p.get("id"): p for p in layout_rooms if isinstance(p, dict)}
    for r in spec["rooms"]:
        p = by_id.get(r["id"])
        if p is None:
            problems.append(f"{r['id']} not placed"); continue
        vals = []
        for k in ("x", "y", "w", "h"):
            u = _q(p[k]) / g
            n = round(u)
            if abs(float(u) - n) > 1e-9:
                problems.append(f"{r['id']}.{k}={p[k]!r} is not a multiple of {cfg['grid_m']:g} m")
            vals.append(n)
        fixed[r["id"]] = tuple(vals)
    if problems:
        return {"status": "OFF_GRID", "raw_status": None, "problems": problems}
    try:
        cp_model, m, _, info = build_model(spec, fixed=fixed, with_objective=False)
    except EmptyDomain as e:
        return {"status": "INFEASIBLE", "raw_status": "EMPTY_DOMAIN", "problems": [str(e)]}
    s = _solver(cp_model, cfg)
    raw = s.status_name(s.solve(m))
    return {"status": map_status(raw, False), "raw_status": raw, "problems": []}
