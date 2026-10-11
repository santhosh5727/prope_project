"""Facility specification: strict validation and normalisation.

The spec is plain JSON-compatible data. ``validate_spec`` never trusts its
input: it collects *all* problems and raises ``SpecError`` listing them, so a
bad input produces a useful explanation instead of a crash or a silent default.

Documented defaults (all are demonstration assumptions, not engineering
standards):
    area_rel_tol       0.02  -> placed area may differ from required by +-2 %
    min_shared_edge_m  1.0   -> two rooms count as adjacent only if they share
                                a boundary segment of at least this length
    geom_eps_m         1e-6  -> numerical tolerance for geometric comparisons
"""
from __future__ import annotations

import math
from copy import deepcopy

DEFAULT_TOLERANCES = {
    "area_rel_tol": 0.02,
    "min_shared_edge_m": 1.0,
    "geom_eps_m": 1e-6,
}

# Provenance tags carried on every input object.
SOURCE_USER = "user"                  # entered/edited by the person using the tool
SOURCE_SYNTHETIC = "synthetic_demo"   # synthetic demonstration value
SOURCE_ASSUMPTION = "assumption"      # modelling assumption of this software
VALID_SOURCES = {SOURCE_USER, SOURCE_SYNTHETIC, SOURCE_ASSUMPTION}

MAX_ROOMS = 30
MAX_MAGNITUDE = 1e6   # metres / square metres: anything larger is rejected as implausible (and avoids float overflow)

# Generator settings. They are modelling choices of this software (tag "assumption"), not engineering data.
DEFAULT_GENERATOR = {
    "method": "heuristic",            # "heuristic" (stdlib baseline) | "cpsat" (needs OR-Tools)
    "grid_m": 0.1,                    # CP-SAT integer grid; coordinates/sizes are multiples of this
    "objective": "feasibility",       # CP-SAT: "feasibility" (fast; any area inside the tolerance band) | "min_area_deviation"
                                      #         | "min_bbox_perimeter" | "min_bbox_area" (compactness; all constraints still hold)
    "time_limit_s": 20.0,             # CP-SAT wall-clock limit; hitting it gives status UNKNOWN or FEASIBLE
    "num_workers": 1,                 # 1 = deterministic search for a given seed/version/platform
    "seed": 1,
    "deterministic_time_limit_s": None,  # CP-SAT: optional work-based limit (OR-Tools "deterministic time"); None = off. See cpsat.py
    "model_options": [],              # CP-SAT opt-in model variants (see cpsat.MODEL_OPTIONS); [] = the documented base model
}
GENERATOR_METHODS = ("heuristic", "cpsat")
GENERATOR_OBJECTIVES = ("feasibility", "min_area_deviation", "min_bbox_perimeter", "min_bbox_area")
GENERATOR_MODEL_OPTIONS = ("tight_domains", "linear_adjacency", "cumulative_cuts", "mirror_symmetry", "twin_symmetry", "heuristic_hint", "core_first")
GENERATOR_FIELDS = tuple(DEFAULT_GENERATOR)


class SpecError(ValueError):
    """Raised when a spec is invalid. ``errors`` holds every problem found."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def tol_source(spec: dict, key: str) -> str:
    """Provenance tag for one tolerance field (user if the user edited that field)."""
    t = spec["tolerances"]
    return SOURCE_USER if key in t.get("user_fields", []) else t["source"]


def gen_source(spec: dict, key: str) -> str:
    """Provenance tag for one generator setting (user if the user edited that field)."""
    g = spec["generator"]
    return SOURCE_USER if key in g.get("user_fields", []) else g["source"]


def _safe_repr(v, limit: int = 60) -> str:
    """repr() that cannot raise (e.g. for integers beyond Python's digit limit) and cannot flood a message."""
    try:
        r = repr(v)
    except Exception:  # noqa: BLE001
        r = f"<{type(v).__name__}>"
    return r if len(r) <= limit else r[:limit] + "..."


def _is_num(v) -> bool:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(v)          # raises OverflowError for integers too large for a float
    except (OverflowError, ValueError):
        return False


def _pos_num(v) -> bool:
    return _is_num(v) and 0 < v <= MAX_MAGNITUDE


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _source(obj, default, path, errors):
    s = obj.get("source", default)
    if not isinstance(s, str) or s not in VALID_SOURCES:     # isinstance first: lists/dicts are unhashable
        errors.append(f"{path}.source: must be one of {sorted(VALID_SOURCES)} (got {_safe_repr(s)})")
        return default
    return s


def validate_spec(raw) -> dict:
    """Validate ``raw`` and return a normalised deep copy (defaults filled in)."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise SpecError(["spec: must be a JSON object"])

    meta = raw.get("meta", {})
    if not isinstance(meta, dict):
        errors.append("meta: must be an object")
        meta = {}
    out = {"meta": {"title": "Untitled facility spec", "label": ""}}
    for key in ("title", "label"):
        v = meta.get(key, out["meta"][key])
        if isinstance(v, str):
            out["meta"][key] = v
        else:
            errors.append(f"meta.{key}: must be a string (got {_safe_repr(v)})")

    # ---- building -------------------------------------------------------
    b = raw.get("building")
    if not isinstance(b, dict):
        errors.append("building: missing or not an object (need width_m and height_m)")
        b = {}
    for key in ("width_m", "height_m"):
        if key not in b:
            errors.append(f"building.{key}: missing")
        elif not _pos_num(b[key]):
            errors.append(f"building.{key}: must be a positive finite number no larger than {MAX_MAGNITUDE:g} (got {_safe_repr(b[key])})")
    out["building"] = {
        "width_m": b.get("width_m"),
        "height_m": b.get("height_m"),
        "source": _source(b, SOURCE_USER, "building", errors),
    }

    # ---- tolerances -----------------------------------------------------
    t = raw.get("tolerances", {})
    if not isinstance(t, dict):
        errors.append("tolerances: must be an object")
        t = {}
    tol = dict(DEFAULT_TOLERANCES)
    for key, default in DEFAULT_TOLERANCES.items():
        if key in t:
            v = t[key]
            ok = _pos_num(v) and (key != "area_rel_tol" or v < 1)
            if not ok:
                lim = " and < 1" if key == "area_rel_tol" else f" no larger than {MAX_MAGNITUDE:g}"
                errors.append(f"tolerances.{key}: must be a positive finite number{lim} (got {_safe_repr(v)})")
            else:
                tol[key] = float(v)
    tol["source"] = _source(t, SOURCE_ASSUMPTION, "tolerances", errors)
    # Per-field provenance: only the listed fields were changed by the user; the rest keep ``source``.
    uf = t.get("user_fields", [])
    if not isinstance(uf, list) or not all(isinstance(k, str) and k in DEFAULT_TOLERANCES for k in uf):
        errors.append(f"tolerances.user_fields: must be a list of tolerance names {sorted(DEFAULT_TOLERANCES)} (got {_safe_repr(uf)})")
        uf = []
    tol["user_fields"] = sorted(set(uf))
    out["tolerances"] = tol

    # ---- generator settings ---------------------------------------------
    graw = raw.get("generator", {})
    if not isinstance(graw, dict):
        errors.append("generator: must be an object")
        graw = {}
    gen = dict(DEFAULT_GENERATOR)
    gerr = lambda key, msg, v: errors.append(f"generator.{key}: {msg} (got {_safe_repr(v)})")
    if "method" in graw:
        v = graw["method"]
        if isinstance(v, str) and v in GENERATOR_METHODS: gen["method"] = v
        else: gerr("method", f"must be one of {list(GENERATOR_METHODS)}", v)
    if "objective" in graw:
        v = graw["objective"]
        if isinstance(v, str) and v in GENERATOR_OBJECTIVES: gen["objective"] = v
        else: gerr("objective", f"must be one of {list(GENERATOR_OBJECTIVES)}", v)
    if "grid_m" in graw:
        v = graw["grid_m"]
        if _is_num(v) and 0.01 <= v <= 1.0: gen["grid_m"] = float(v)
        else: gerr("grid_m", "must be a number between 0.01 and 1.0 metres", v)
    if "time_limit_s" in graw:
        v = graw["time_limit_s"]
        if _is_num(v) and 0.01 <= v <= 120: gen["time_limit_s"] = float(v)
        else: gerr("time_limit_s", "must be a number between 0.01 and 120 seconds", v)
    if "num_workers" in graw:
        v = graw["num_workers"]
        if _is_int(v) and 1 <= v <= 8: gen["num_workers"] = v
        else: gerr("num_workers", "must be an integer between 1 and 8", v)
    if "seed" in graw:
        v = graw["seed"]
        if _is_int(v) and 0 <= v < 2 ** 31: gen["seed"] = v
        else: gerr("seed", "must be an integer between 0 and 2147483647", v)
    if "deterministic_time_limit_s" in graw:
        v = graw["deterministic_time_limit_s"]
        if v is None: gen["deterministic_time_limit_s"] = None
        elif _is_num(v) and 0.001 <= v <= 100000: gen["deterministic_time_limit_s"] = float(v)
        else: gerr("deterministic_time_limit_s", "must be null or a number between 0.001 and 100000", v)
    if "model_options" in graw:
        v = graw["model_options"]
        if isinstance(v, list) and all(isinstance(o, str) and o in GENERATOR_MODEL_OPTIONS for o in v):
            gen["model_options"] = sorted(set(v))
        else: gerr("model_options", f"must be a list of names from {list(GENERATOR_MODEL_OPTIONS)}", v)
    gen["source"] = _source(graw, SOURCE_ASSUMPTION, "generator", errors)
    gu = graw.get("user_fields", [])
    if not isinstance(gu, list) or not all(isinstance(k, str) and k in GENERATOR_FIELDS for k in gu):
        gerr("user_fields", f"must be a list of generator setting names {list(GENERATOR_FIELDS)}", gu)
        gu = []
    gen["user_fields"] = sorted(set(gu))
    out["generator"] = gen

    # ---- rooms ----------------------------------------------------------
    rooms_raw = raw.get("rooms")
    rooms: list[dict] = []
    ids: set[str] = set()
    if not isinstance(rooms_raw, list) or not rooms_raw:
        errors.append("rooms: must be a non-empty list")
        rooms_raw = []
    elif len(rooms_raw) > MAX_ROOMS:
        errors.append(f"rooms: at most {MAX_ROOMS} rooms are supported by this slice (got {len(rooms_raw)})")
        rooms_raw = rooms_raw[:MAX_ROOMS]
    for i, r in enumerate(rooms_raw):
        p = f"rooms[{i}]"
        if not isinstance(r, dict):
            errors.append(f"{p}: must be an object")
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid.strip():
            errors.append(f"{p}.id: must be a non-empty string (got {_safe_repr(rid)})")
            rid = f"?{i}"
        elif rid in ids:
            errors.append(f"{p}.id: duplicate room id {_safe_repr(rid)}")
        ids.add(rid)
        name = r.get("name", rid)
        if not isinstance(name, str):
            errors.append(f"{p}.name: must be a string")
            name = rid
        area = r.get("area_m2")
        if "area_m2" not in r:
            errors.append(f"{p} ({rid}).area_m2: missing")
        elif not _pos_num(area):
            errors.append(f"{p} ({rid}).area_m2: must be a positive finite number no larger than {MAX_MAGNITUDE:g} (got {_safe_repr(area)})")
        md = r.get("min_dim_m")
        if md is not None and not _pos_num(md):
            errors.append(f"{p} ({rid}).min_dim_m: must be a positive finite number or omitted (got {_safe_repr(md)})")
            md = None
        rooms.append({
            "id": rid,
            "name": name,
            "area_m2": area,
            "min_dim_m": md,
            "source": _source(r, SOURCE_USER, p, errors),
        })
    out["rooms"] = rooms

    # ---- adjacency ------------------------------------------------------
    adj_raw = raw.get("adjacency", [])
    adjs: list[dict] = []
    if not isinstance(adj_raw, list):
        errors.append("adjacency: must be a list")
        adj_raw = []
    adj_ids: set[str] = set()
    pairs: set[frozenset] = set()
    for i, a in enumerate(adj_raw):
        p = f"adjacency[{i}]"
        if not isinstance(a, dict):
            errors.append(f"{p}: must be an object")
            continue
        aid = a.get("id", f"ADJ-{i + 1:02d}")
        if not isinstance(aid, str) or not aid.strip():
            errors.append(f"{p}.id: must be a non-empty string")
            aid = f"ADJ-?{i}"
        elif aid in adj_ids:
            errors.append(f"{p}.id: duplicate adjacency id {_safe_repr(aid)}")
        adj_ids.add(aid)
        ra, rb = a.get("a"), a.get("b")
        for label, val in (("a", ra), ("b", rb)):
            if not isinstance(val, str) or val not in ids:   # isinstance first: lists/dicts are unhashable
                errors.append(f"{p} ({aid}).{label}: unknown room id {_safe_repr(val)}")
        if isinstance(ra, str) and ra == rb:
            errors.append(f"{p} ({aid}): a room cannot be adjacent to itself ({_safe_repr(ra)})")
        elif isinstance(ra, str) and isinstance(rb, str) and ra in ids and rb in ids:
            key = frozenset((ra, rb))
            if key in pairs:
                errors.append(f"{p} ({aid}): duplicate requirement for pair {_safe_repr(ra)}/{_safe_repr(rb)}")
            pairs.add(key)
        adjs.append({"id": aid, "a": ra, "b": rb, "source": _source(a, SOURCE_USER, p, errors)})
    out["adjacency"] = adjs

    if errors:
        raise SpecError(errors)
    return deepcopy(out)
