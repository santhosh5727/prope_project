"""Deterministic baseline layout generator (row-based / shelf packing).

Heuristic, in plain words:
  1. Pre-check (tolerance-aware, see ``precheck``): the smallest accepted total
     area fits the building, and every room can fit its own minimum dimension
     at its largest accepted area. If not, return ``status="infeasible"`` with
     reasons and NO placements (nothing is silently squeezed in).
  2. Order rooms so that rooms with adjacency requirements sit next to each
     other in a chain (depth-first from the least-connected room).
  3. Cut that order into k contiguous rows (k = 1..6). Each row spans the full
     building width; its height is (sum of its room areas) / building width,
     so every room gets EXACTLY its required area (all areas are scaled down
     uniformly, within the accepted tolerance, only if the exact total would not
     fit the building). Room width = area / height.
  4. Try every cut position and both left-to-right and serpentine row
     direction (alternate rows reversed, so chain neighbours at row ends stack
     vertically). Keep the candidate with the fewest minimum-dimension
     violations, then the fewest unsatisfied adjacencies, then fewest rows.
  5. Space left over at the bottom of the building is reported as
     ``unallocated_area_m2``; it is not assigned to any room.

The generator reports what it *believes* it achieved (``self_report``). That
report is NOT authoritative: ``validator.py`` re-checks the output from
scratch and is the only source of pass/fail.

Search is capped (``MAX_CANDIDATES``) so large specs cannot hang the server.
This module deliberately does not import the validator, and the adjacency
test below is a separate implementation from the validator's.

``generate_layout(spec, method=None)`` is the single entry point. ``method`` (default: ``spec["generator"]["method"]``,
which defaults to ``"heuristic"``) selects this module's row-packing baseline or the CP-SAT generator in ``cpsat.py``.
``precheck`` holds the cheap, mathematically sound infeasibility tests shared by both. Generation status values:
  placed              a candidate layout was produced (it is NOT yet known to be valid: the validator decides)
  infeasible          proven impossible in continuous space by an arithmetic pre-check
  infeasible_on_grid  CP-SAT proved the *discretised model* infeasible; says nothing about off-grid layouts
  unknown             CP-SAT stopped without a conclusion (e.g. time limit); NOT a claim of infeasibility
  error               configuration/modelling error (CP-SAT MODEL_INVALID, OR-Tools missing, grid unusable)
"""
from __future__ import annotations

from itertools import combinations

MAX_ROWS = 6
MAX_CANDIDATES = 20000


def _chain_order(rooms: list[dict], adjacency: list[dict]) -> list[dict]:
    """Rooms with adjacency requirements first, as DFS chains; others after."""
    index = {r["id"]: i for i, r in enumerate(rooms)}
    nbrs: dict[str, list[str]] = {r["id"]: [] for r in rooms}
    for a in adjacency:
        nbrs[a["a"]].append(a["b"])
        nbrs[a["b"]].append(a["a"])
    for k in nbrs:
        nbrs[k].sort(key=index.__getitem__)

    seen: set[str] = set()
    comps: list[list[str]] = []
    for r in rooms:
        rid = r["id"]
        if rid in seen or not nbrs[rid]:
            continue
        # collect component
        comp, stack = [], [rid]
        members = set()
        while stack:
            cur = stack.pop()
            if cur in members:
                continue
            members.add(cur)
            stack.extend(nbrs[cur])
        start = min(members, key=lambda m: (len(nbrs[m]), index[m]))
        order: list[str] = []

        def dfs(n: str) -> None:
            seen.add(n)
            order.append(n)
            for m in nbrs[n]:
                if m not in seen:
                    dfs(m)

        dfs(start)
        comps.append(order)
    comps.sort(key=lambda c: -len(c))  # stable: larger chains first

    by_id = {r["id"]: r for r in rooms}
    ordered = [by_id[i] for comp in comps for i in comp]
    ordered += [r for r in rooms if r["id"] not in seen and not nbrs[r["id"]]]
    return ordered


def _place_rows(rows: list[list[dict]], width: float, serpentine: bool) -> list[dict]:
    placed, y = [], 0.0
    for i, row in enumerate(rows):
        h = sum(r["area_m2"] for r in row) / width
        seq = list(reversed(row)) if (serpentine and i % 2 == 1) else row
        x = 0.0
        for r in seq:
            w = r["area_m2"] / h
            placed.append({"id": r["id"], "x": round(x, 9), "y": round(y, 9),
                           "w": round(w, 9), "h": round(h, 9)})
            x += w
        y += h
    return placed


def _contact_len(a: dict, b: dict, eps: float) -> float:
    """Length of shared boundary between two rectangles (0 if none/overlap)."""
    ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if ox > eps and oy > eps:
        return 0.0
    if abs(a["x"] + a["w"] - b["x"]) <= eps or abs(b["x"] + b["w"] - a["x"]) <= eps:
        return max(oy, 0.0)
    if abs(a["y"] + a["h"] - b["y"]) <= eps or abs(b["y"] + b["h"] - a["y"]) <= eps:
        return max(ox, 0.0)
    return 0.0


def _evaluate(placed, rooms_by_id, adjacency, min_edge, eps):
    pos = {p["id"]: p for p in placed}
    md_bad = [p["id"] for p in placed
              if rooms_by_id[p["id"]]["min_dim_m"] is not None
              and min(p["w"], p["h"]) < rooms_by_id[p["id"]]["min_dim_m"] - eps]
    adj_bad = [a["id"] for a in adjacency
               if _contact_len(pos[a["a"]], pos[a["b"]], eps) < min_edge - eps]
    return md_bad, adj_bad


def precheck(spec: dict, include_adjacency: bool = True) -> list[str]:
    """Cheap infeasibility tests that hold in CONTINUOUS space (no grid). Returns reasons ([] = not ruled out).

    Soundness argument for each test (rule numbers refer to validator.py):
      * every room must have area >= required x (1 - tol) (V-06) and rooms are disjoint inside the building
        (V-04, V-05), so sum(required) x (1 - tol) <= W x H is necessary;
      * a room with both sides >= m has area >= m x m, and area <= required x (1 + tol), so
        m x m <= required x (1 + tol) is necessary; and m <= min(W, H) is necessary;
      * a shared wall of length L lies along a building side, so L <= max(W, H) is necessary for any adjacency.
    The 1e-9 relative slack and the geometric eps mirror the validator's own numerical slack.
    """
    W, H = float(spec["building"]["width_m"]), float(spec["building"]["height_m"])
    tol = spec["tolerances"]
    eps, tol_a, min_edge = tol["geom_eps_m"], tol["area_rel_tol"], tol["min_shared_edge_m"]
    slack = 1e-9
    rooms = spec["rooms"]
    reasons: list[str] = []
    total = sum(r["area_m2"] for r in rooms)
    min_total = total * (1 - tol_a)
    if min_total > W * H + eps:
        reasons.append(
            f"Total required room area {total:.2f} m2 exceeds building area {W * H:.2f} m2 "
            f"({W:g} x {H:g} m) even at the smallest accepted room areas ({min_total:.2f} m2 = required x "
            f"(1 - {tol_a * 100:g} %)). Enlarge the building or reduce room areas.")
    for r in rooms:
        m = r["min_dim_m"]
        if m is None:
            continue
        a_max = r["area_m2"] * (1 + tol_a) * (1 + slack)
        if m > min(W, H) + eps:
            reasons.append(f"Room {r['id']}: minimum dimension {m:g} m exceeds the shorter building side {min(W, H):g} m.")
        elif m * m > a_max + eps:
            reasons.append(
                f"Room {r['id']}: even at its largest accepted area ({a_max:.4g} m2) it is smaller than "
                f"{m:g} x {m:g} = {m * m:g} m2, so it cannot have both sides >= its minimum dimension {m:g} m.")
    if include_adjacency and spec["adjacency"] and min_edge > max(W, H) + eps:
        reasons.append(
            f"Adjacency requires a shared wall of at least {min_edge:g} m, which is longer than both building sides "
            f"({W:g} x {H:g} m).")
    return reasons


def infeasible_result(reasons: list[str], method_name: str) -> dict:
    return {
        "status": "infeasible", "rooms": [], "reasons": reasons,
        "infeasibility_scope": "continuous space (arithmetic pre-check)",
        "self_report": {"unsatisfied_adjacency": None, "min_dim_violations": None},
        "unallocated_area_m2": None,
        "method": {"name": method_name, "candidates_evaluated": 0, "search_truncated": False},
        "solver": None,
    }


def generate_heuristic(spec: dict) -> dict:
    """Row-packing baseline. ``spec`` must already be validated by ``spec.validate_spec``."""
    W = float(spec["building"]["width_m"])
    H = float(spec["building"]["height_m"])
    tol = spec["tolerances"]
    eps, min_edge = tol["geom_eps_m"], tol["min_shared_edge_m"]
    rooms, adjacency = spec["rooms"], spec["adjacency"]
    rooms_by_id = {r["id"]: r for r in rooms}

    # The heuristic's own adjacency behaviour is unchanged: an unreachable shared-wall length is reported as
    # unsatisfied adjacency in the layout, not as pre-check infeasibility.
    reasons = precheck(spec, include_adjacency=False)
    if reasons:
        return infeasible_result(reasons, "row-based shelf packing")

    total_req = sum(r["area_m2"] for r in rooms)
    scale = min(1.0, W * H / total_req)   # < 1 only when the exact total does not fit; precheck guarantees >= 1 - tol
    placed_rooms = [{**r, "area_m2": r["area_m2"] * scale} for r in rooms] if scale < 1.0 else rooms
    total = total_req * scale

    order = _chain_order(placed_rooms, adjacency)
    n = len(order)
    best = None  # (key, placed, md_bad, adj_bad, k, serp)
    evaluated, truncated = 0, False
    for k in range(1, min(n, MAX_ROWS) + 1):
        for cuts in combinations(range(1, n), k - 1):
            bounds = (0, *cuts, n)
            rows = [order[bounds[i]:bounds[i + 1]] for i in range(k)]
            for serp in (False, True) if k > 1 else (False,):
                if evaluated >= MAX_CANDIDATES:
                    truncated = True
                    break
                evaluated += 1
                placed = _place_rows(rows, W, serp)
                md_bad, adj_bad = _evaluate(placed, rooms_by_id, adjacency, min_edge, eps)
                key = (len(md_bad), len(adj_bad), k, serp)
                if best is None or key < best[0]:
                    best = (key, placed, md_bad, adj_bad, k, serp)
            if truncated:
                break
        if truncated:
            break

    _, placed, md_bad, adj_bad, k, serp = best
    used_h = total / W
    return {
        "status": "placed",
        "rooms": placed,
        "reasons": [],
        "self_report": {"unsatisfied_adjacency": adj_bad, "min_dim_violations": md_bad},
        "unallocated_area_m2": round(W * H - total, 6),
        "method": {
            "name": "row-based shelf packing",
            "rows": k,
            "serpentine": serp,
            "used_height_m": round(used_h, 6),
            "candidates_evaluated": evaluated,
            "search_truncated": truncated,
            "area_scale": round(scale, 9),
        },
        "solver": None,
    }


def generate_layout(spec: dict, method: str | None = None) -> dict:
    """Single generator entry point; see the module docstring for the result contract.

    ``method`` overrides ``spec["generator"]["method"]`` (default "heuristic")."""
    chosen = method or spec.get("generator", {}).get("method", "heuristic")
    if chosen == "heuristic":
        return generate_heuristic(spec)
    if chosen == "cpsat":
        from . import cpsat   # lazy: OR-Tools is an optional dependency
        return cpsat.generate_cpsat(spec)
    return {
        "status": "error", "rooms": [], "reasons": [f"unknown generator method {chosen!r}"],
        "self_report": {"unsatisfied_adjacency": None, "min_dim_violations": None},
        "unallocated_area_m2": None, "method": {"name": str(chosen)},
        "solver": {"status": "MODEL_INVALID", "raw_status": None, "elapsed_s": 0.0},
    }
