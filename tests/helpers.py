import json
from pathlib import Path

from pharma_layout.spec import validate_spec

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "synthetic_osd_demo.json"


def demo_raw() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def make_spec(rooms, adjacency=None, W=20.0, H=10.0, **tol):
    """rooms: list of (id, area[, min_dim]). adjacency: list of (a, b)."""
    raw = {
        "building": {"width_m": W, "height_m": H},
        "rooms": [{"id": r[0], "name": r[0].title(), "area_m2": r[1],
                   **({"min_dim_m": r[2]} if len(r) > 2 else {})} for r in rooms],
        "adjacency": [{"id": f"ADJ-{i + 1:02d}", "a": a, "b": b} for i, (a, b) in enumerate(adjacency or [])],
    }
    if tol:
        raw["tolerances"] = tol
    return validate_spec(raw)


def rect(rid, x, y, w, h):
    return {"id": rid, "x": x, "y": y, "w": w, "h": h}


def result(validation, rule_id):
    for r in validation["results"]:
        if r["rule_id"] == rule_id:
            return r
    raise KeyError(rule_id)
