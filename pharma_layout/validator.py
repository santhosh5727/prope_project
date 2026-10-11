"""Independent layout validator.

Takes a *validated spec* and a list of placed rooms and re-checks everything
from first principles. It does not import the generator and does not look at
any status the generator reported.

What these checks establish: only the specific, encoded geometric and input
constraints listed below, on the inputs given. They do NOT establish
pharmaceutical, GMP, fire-safety or any other regulatory compliance.

Geometry conventions: x to the right, y downward, origin at the building's
top-left corner; a room is the axis-aligned rectangle [x, x+w] x [y, y+h].

Rule catalogue
  V-01  Placement well-formed and complete (each spec room placed once)
  V-02  Smallest accepted total area (sum of required x (1 - area_rel_tol)) <= building area (input consistency)
  V-03  Every placed room has positive width and height
  V-04  Every placed room lies inside the building boundary
  V-05  No two rooms overlap (interior overlap > eps in both axes)
  V-06  Placed area within relative tolerance of required area
  V-07  Minimum room dimension (shorter side) respected
  V-08  One result per adjacency requirement. DEFINITION: rooms A and B are
        adjacent iff their interiors do not overlap AND they share a boundary
        segment (touching edges) of length >= min_shared_edge_m. Touching at
        a corner only, or a gap of more than eps, is NOT adjacent.
"""
from __future__ import annotations

import math

from .spec import tol_source

PASS, FAIL, NA = "PASS", "FAIL", "N/A"

# V-06 compares a relative deviation with area_rel_tol. Layout coordinates are floats (e.g. 10.2 may arrive as
# 10.200000000000001), so a room exactly at the tolerance limit could be rejected by round-off alone. A relative
# slack of 1e-9 (about 3e-8 m2 on a 30 m2 room) absorbs that and nothing else.
AREA_REL_SLACK = 1e-9


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _res(rule_id, title, description, inputs, result, explanation, offenders=None, **extra):
    d = {
        "rule_id": rule_id,
        "title": title,
        "description": description,
        "inputs": inputs,            # list of {name, value, source}
        "result": result,
        "explanation": explanation,
        "offenders": sorted(set(offenders or [])),
    }
    d.update(extra)
    return d


def _inp(name, value, source):
    return {"name": name, "value": value, "source": source}


def _clean_layout(spec, layout_rooms):
    """Return (placed: dict id -> rect dict, problems: list[str])."""
    known = {r["id"] for r in spec["rooms"]}
    placed, problems = {}, []
    if not isinstance(layout_rooms, list):
        return {}, ["layout rooms must be a list"]
    for i, p in enumerate(layout_rooms):
        if not isinstance(p, dict):
            problems.append(f"entry {i} is not an object")
            continue
        rid = p.get("id")
        if rid not in known:
            problems.append(f"entry {i}: room id {rid!r} is not in the spec")
            continue
        if rid in placed:
            problems.append(f"room {rid} is placed more than once")
            continue
        if not all(_num(p.get(k)) for k in ("x", "y", "w", "h")):
            problems.append(f"room {rid}: x, y, w, h must all be finite numbers")
            continue
        placed[rid] = {"id": rid, "x": float(p["x"]), "y": float(p["y"]),
                       "w": float(p["w"]), "h": float(p["h"])}
    return placed, problems


def _overlap_axes(a, b):
    ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    return ox, oy


def _gap(a, b):
    """Closest distance between two rectangles (0 if touching/overlapping)."""
    dx = max(b["x"] - (a["x"] + a["w"]), a["x"] - (b["x"] + b["w"]), 0.0)
    dy = max(b["y"] - (a["y"] + a["h"]), a["y"] - (b["y"] + b["h"]), 0.0)
    return math.hypot(dx, dy)


def _adjacency(a, b, eps):
    """Return (contact_length, kind) where kind in
    {'overlap','edge','corner','gap'}; contact_length is 0 unless kind=='edge'."""
    ox, oy = _overlap_axes(a, b)
    if ox > eps and oy > eps:
        return 0.0, "overlap"
    vertical_edge = (abs(a["x"] + a["w"] - b["x"]) <= eps or abs(b["x"] + b["w"] - a["x"]) <= eps)
    horizontal_edge = (abs(a["y"] + a["h"] - b["y"]) <= eps or abs(b["y"] + b["h"] - a["y"]) <= eps)
    length = 0.0
    if vertical_edge and oy > 0:
        length = max(length, oy)
    if horizontal_edge and ox > 0:
        length = max(length, ox)
    if length > eps:
        return length, "edge"
    if (vertical_edge or horizontal_edge) and (ox >= -eps and oy >= -eps):
        return 0.0, "corner"
    return 0.0, "gap"


def validate_layout(spec: dict, layout_rooms) -> dict:
    W, H = spec["building"]["width_m"], spec["building"]["height_m"]
    b_src = spec["building"]["source"]
    tol = spec["tolerances"]
    eps, tol_a, min_edge = tol["geom_eps_m"], tol["area_rel_tol"], tol["min_shared_edge_m"]
    src_eps, src_area, src_edge = (tol_source(spec, k) for k in ("geom_eps_m", "area_rel_tol", "min_shared_edge_m"))
    rooms = {r["id"]: r for r in spec["rooms"]}
    placed, problems = _clean_layout(spec, layout_rooms)
    results: list[dict] = []

    # ---- V-01 completeness ------------------------------------------------
    missing = [rid for rid in rooms if rid not in placed]
    bad = problems + ([f"not placed: {', '.join(missing)}"] if missing else [])
    results.append(_res(
        "V-01", "Placement complete and well-formed",
        "Every room in the spec is placed exactly once with finite x, y, w, h; no unknown or duplicate rooms.",
        [_inp("rooms required", len(rooms), "spec"), _inp("rooms placed", len(placed), "layout")],
        FAIL if bad else PASS,
        ("; ".join(bad) if bad else f"All {len(rooms)} rooms are placed exactly once."),
        offenders=missing))

    # ---- V-02 total area --------------------------------------------------
    # Every room may legally be built as small as required x (1 - tol) (rule V-06), so the input-consistency
    # question is whether THAT total fits, not whether the exact required total fits.
    total = sum(r["area_m2"] for r in rooms.values())
    min_total = total * (1 - tol_a)
    bld = W * H
    ok = min_total <= bld + eps
    if total <= bld + eps:
        v02 = f"{total:.2f} m2 required vs {bld:.2f} m2 available ({100 * total / bld:.1f} % of building area)."
    elif ok:
        v02 = (f"{total:.2f} m2 required exceeds the {bld:.2f} m2 building, but the smallest accepted total is "
               f"{min_total:.2f} m2 (required x (1 - {tol_a * 100:g} %)), so a fit is possible only with rooms "
               f"built below their required areas.")
    else:
        v02 = (f"Required {total:.2f} m2 exceeds building {bld:.2f} m2 by {total - bld:.2f} m2, and so does the smallest "
               f"accepted total ({min_total:.2f} m2 = required x (1 - {tol_a * 100:g} %)): no layout can satisfy all areas.")
    results.append(_res(
        "V-02", "Total required area fits the building",
        "Sum of the smallest accepted room areas (required x (1 - area_rel_tol)) must not exceed building width x height "
        "(input consistency check).",
        [_inp("building", f"{W:g} x {H:g} m = {bld:.2f} m2", b_src),
         _inp("sum of required areas", f"{total:.2f} m2", "rooms"),
         _inp("area_rel_tol", f"{tol_a * 100:g} %", src_area)],
        PASS if ok else FAIL, v02))

    geo = [p for p in placed.values()]

    def none_placed(rule_id, title, desc, inputs):
        return _res(rule_id, title, desc, inputs, NA, "No rooms were placed, so there is nothing to check.")

    # ---- V-03 positive dimensions ----------------------------------------
    d3 = "Each placed room must have width > 0 and height > 0."
    if not geo:
        results.append(none_placed("V-03", "Positive dimensions", d3, []))
    else:
        nonpos = [p["id"] for p in geo if p["w"] <= 0 or p["h"] <= 0]
        results.append(_res(
            "V-03", "Positive dimensions", d3, [_inp("rooms checked", len(geo), "layout")],
            FAIL if nonpos else PASS,
            (f"Non-positive width/height: " + ", ".join(
                f"{i} ({placed[i]['w']:g} x {placed[i]['h']:g} m)" for i in nonpos)
             if nonpos else "All placed rooms have positive width and height."),
            offenders=nonpos))

    # ---- V-04 boundary ----------------------------------------------------
    d4 = "Each room rectangle must lie within [0, width] x [0, height]."
    in4 = [_inp("building", f"{W:g} x {H:g} m", b_src), _inp("eps", f"{eps:g} m", src_eps)]
    if not geo:
        results.append(none_placed("V-04", "Inside building boundary", d4, in4))
    else:
        out, msgs = [], []
        for p in geo:
            over = []
            if p["x"] < -eps: over.append(f"left edge {-p['x']:.3f} m outside")
            if p["y"] < -eps: over.append(f"top edge {-p['y']:.3f} m outside")
            if p["x"] + p["w"] > W + eps: over.append(f"right edge {p['x'] + p['w'] - W:.3f} m outside")
            if p["y"] + p["h"] > H + eps: over.append(f"bottom edge {p['y'] + p['h'] - H:.3f} m outside")
            if over:
                out.append(p["id"])
                msgs.append(f"{p['id']}: " + ", ".join(over))
        results.append(_res("V-04", "Inside building boundary", d4, in4,
                            FAIL if out else PASS,
                            "; ".join(msgs) if out else "All placed rooms are within the building boundary.",
                            offenders=out))

    # ---- V-05 overlap -----------------------------------------------------
    d5 = "No two room interiors may overlap (overlap extent > eps in both x and y)."
    in5 = [_inp("eps", f"{eps:g} m", src_eps)]
    if len(geo) < 2:
        results.append(_res("V-05", "No overlaps", d5, in5, NA if not geo else PASS,
                            "Fewer than two rooms placed; no pairs to compare." if not geo
                            else "Only one room placed; no pairs to compare."))
    else:
        pairs, offenders = [], []
        for i in range(len(geo)):
            for j in range(i + 1, len(geo)):
                ox, oy = _overlap_axes(geo[i], geo[j])
                if ox > eps and oy > eps:
                    pairs.append(f"{geo[i]['id']} and {geo[j]['id']} overlap by {ox * oy:.3f} m2 ({ox:.3f} x {oy:.3f} m)")
                    offenders += [geo[i]["id"], geo[j]["id"]]
        results.append(_res("V-05", "No overlaps", d5, in5, FAIL if pairs else PASS,
                            "; ".join(pairs) if pairs else f"Checked {len(geo) * (len(geo) - 1) // 2} room pairs; none overlap.",
                            offenders=offenders))

    # ---- V-06 area tolerance ---------------------------------------------
    d6 = ("Placed area (w x h) must be within the relative tolerance of the required area "
          f"(numerical slack {AREA_REL_SLACK:g} relative, for float round-off only).")
    in6 = [_inp("area_rel_tol", f"{tol_a * 100:g} %", src_area)]
    if not geo:
        results.append(none_placed("V-06", "Required areas satisfied", d6, in6))
    else:
        bad6, notes = [], []
        for p in geo:
            req = rooms[p["id"]]["area_m2"]
            got = p["w"] * p["h"]
            dev = (got - req) / req
            if abs(dev) > tol_a + AREA_REL_SLACK:
                bad6.append(p["id"])
                notes.append(f"{p['id']}: placed {got:.2f} m2 vs required {req:g} m2 ({dev * 100:+.1f} %)")
        results.append(_res("V-06", "Required areas satisfied", d6, in6, FAIL if bad6 else PASS,
                            "; ".join(notes) if bad6 else f"All {len(geo)} placed areas are within +-{tol_a * 100:g} % of the required area.",
                            offenders=bad6))

    # ---- V-07 minimum dimension ------------------------------------------
    d7 = "The shorter side of each room must be >= its minimum dimension (rooms without one are skipped)."
    spec_md = {i: r["min_dim_m"] for i, r in rooms.items() if r["min_dim_m"] is not None}
    in7 = [_inp("rooms with min_dim_m", len(spec_md), "rooms")]
    checked = [p for p in geo if p["id"] in spec_md]
    if not checked:
        results.append(_res("V-07", "Minimum room dimensions", d7, in7, NA,
                            "No placed room has a minimum dimension specified."))
    else:
        bad7, notes = [], []
        for p in checked:
            m, short = spec_md[p["id"]], min(p["w"], p["h"])
            if short < m - eps:
                bad7.append(p["id"])
                notes.append(f"{p['id']}: shorter side {short:.2f} m < minimum {m:g} m")
        results.append(_res("V-07", "Minimum room dimensions", d7, in7, FAIL if bad7 else PASS,
                            "; ".join(notes) if bad7 else f"All {len(checked)} rooms with a minimum dimension meet it.",
                            offenders=bad7))

    # ---- V-08 adjacency (one row per requirement) ------------------------
    d8 = (f"Rooms share a boundary segment of at least {min_edge:g} m with non-overlapping interiors "
          "(corner contact or a gap does not count).")
    for a in spec["adjacency"]:
        ia, ib = a["a"], a["b"]
        inputs = [_inp(f"requirement {a['id']}", f"{ia} adjacent to {ib}", a["source"]),
                  _inp("min_shared_edge_m", f"{min_edge:g} m", src_edge)]
        rid = f"V-08:{a['id']}"
        title = f"Adjacency {ia} - {ib}"
        if ia not in placed or ib not in placed:
            absent = [x for x in (ia, ib) if x not in placed]
            results.append(_res(rid, title, d8, inputs, FAIL,
                                f"Cannot be satisfied: {', '.join(absent)} not placed.",
                                offenders=[ia, ib], pair=[ia, ib], satisfied=False))
            continue
        length, kind = _adjacency(placed[ia], placed[ib], eps)
        satisfied = kind == "edge" and length >= min_edge - eps
        if satisfied:
            msg = f"{ia} and {ib} share a {length:.2f} m boundary (required >= {min_edge:g} m)."
        elif kind == "overlap":
            msg = f"{ia} and {ib} overlap, so adjacency is not meaningful (see V-05)."
        elif kind == "edge":
            msg = f"{ia} and {ib} share only {length:.2f} m of boundary; at least {min_edge:g} m is required."
        elif kind == "corner":
            msg = f"{ia} and {ib} touch only at a corner (0 m shared boundary); at least {min_edge:g} m is required."
        else:
            msg = f"{ia} and {ib} are separated; closest approach is {_gap(placed[ia], placed[ib]):.2f} m (need a shared boundary of >= {min_edge:g} m)."
        results.append(_res(rid, title, d8, inputs, PASS if satisfied else FAIL, msg,
                            offenders=[] if satisfied else [ia, ib], pair=[ia, ib], satisfied=satisfied,
                            contact_m=round(length, 6)))

    n_fail = sum(1 for r in results if r["result"] == FAIL)
    n_pass = sum(1 for r in results if r["result"] == PASS)
    per_room: dict[str, list[str]] = {}
    for r in results:
        if r["result"] == FAIL:
            for rid in r["offenders"]:
                per_room.setdefault(rid, []).append(r["rule_id"])
    return {
        "overall": FAIL if n_fail else PASS,
        "summary": {"total": len(results), "passed": n_pass, "failed": n_fail,
                    "not_applicable": len(results) - n_pass - n_fail},
        "results": results,
        "per_room_failures": per_room,
    }
