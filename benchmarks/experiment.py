"""Run CP-SAT (or the heuristic) on saved benchmark specs with explicit settings; write ONE new JSON file per run.

Experiments live here, outside the unit-test suite. Existing records (benchmarks/results.json) are never touched:
output goes to benchmarks/runs/<name>.json (refuses to overwrite).

  ./.venv/bin/python benchmarks/experiment.py NAME --cases 15,20,21,22 [--method cpsat|heuristic] \
        [--set time_limit_s=20 --set objective=feasibility ...]      # any spec.generator field, incl. experimental options
Per case it records: generation status, solver status/raw status, wall seconds, validator verdict, a layout hash and
compactness figures computed here (not by the solver): bounding-box area, bbox/total-room-area, bbox/building-area.
"""
import argparse, copy, hashlib, json, os, platform, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from pharma_layout import cpsat
from pharma_layout.pipeline import run_pipeline


def load_specs(folder="specs"):
    man = json.loads((HERE / folder / "MANIFEST.json").read_text())["specs"]
    return [(m["index"], m["case"], json.loads((HERE / folder / m["file"]).read_text())) for m in man]


def coerce(v):
    for f in (int, float):
        try: return f(v)
        except ValueError: pass
    return {"true": True, "false": False, "none": None}.get(v.lower(), v)


def layout_metrics(rooms, spec):
    if not rooms: return None
    x1 = max(r["x"] + r["w"] for r in rooms); y1 = max(r["y"] + r["h"] for r in rooms)
    x0 = min(r["x"] for r in rooms); y0 = min(r["y"] for r in rooms)
    bbox = (x1 - x0) * (y1 - y0); used = sum(r["w"] * r["h"] for r in rooms)
    B = spec["building"]["width_m"] * spec["building"]["height_m"]
    return {"bbox_w": round(x1 - x0, 4), "bbox_h": round(y1 - y0, 4), "bbox_area": round(bbox, 3),
            "bbox_over_rooms": round(bbox / used, 4), "bbox_over_building": round(bbox / B, 4), "rooms_area": round(used, 3)}


def layout_hash(rooms):
    return hashlib.sha256(json.dumps([[r["id"], r["x"], r["y"], r["w"], r["h"]] for r in rooms]).encode()).hexdigest()[:16] if rooms else None


def run_case(idx, name, raw, method, overrides):
    raw = copy.deepcopy(raw)
    if overrides: raw.setdefault("generator", {}).update(overrides)
    hint_valid = None
    if "heuristic_hint" in (raw.get("generator") or {}).get("model_options", []):      # was the hinted heuristic layout itself valid? (validator verdict)
        hint_valid = run_pipeline(copy.deepcopy(raw), method="heuristic")["validation"]["overall"] == "PASS"
    t0 = time.perf_counter(); res = run_pipeline(raw, method=method); wall = time.perf_counter() - t0
    g, v = res["generation"], res["validation"]
    rooms = g.get("rooms") or []
    sol = g.get("solver") or {}
    return {"index": idx, "case": name, "generation": g["status"], "validator": v["overall"],
            "solver_status": sol.get("status"), "raw_status": sol.get("raw_status"), "wall_s": round(wall, 3),
            "solve_s": sol.get("solve_s"), "objective_value": sol.get("objective_value"),
            "best_objective_bound": sol.get("best_objective_bound"), "table_rows": sol.get("table_rows"),
            "heuristic_hint_valid": hint_valid, "core": sol.get("core"), "layout_hash": layout_hash(rooms), "metrics": layout_metrics(rooms, raw) if g["status"] == "placed" else None,
            "failed_rules": [r["rule_id"] for r in v["results"] if r["result"] == "FAIL"][:6] if g["status"] == "placed" else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("--cases", default="all"); ap.add_argument("--method", default="cpsat")
    ap.add_argument("--set", action="append", default=[]); ap.add_argument("--note", default="")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--seeds", default=None, help="comma list: solve every case once per solver seed (overrides --set seed=)")
    ap.add_argument("--specs", default="specs", help="spec folder under benchmarks/: specs (saved, reconstructed) | specs_holdout")
    a = ap.parse_args()
    out = HERE / "runs" / f"{a.name}.json"
    if out.exists(): sys.exit(f"{out} exists; pick a new name (runs are never overwritten)")
    overrides = {k: ([x for x in v.split(",") if x] if k == "model_options" else coerce(v)) for k, v in (s.split("=", 1) for s in a.set)}
    specs = load_specs(a.specs)
    if a.cases != "all": want = {int(c) for c in a.cases.split(",")}; specs = [s for s in specs if s[0] in want]
    caps = cpsat.capabilities()
    meta = {"name": a.name, "note": a.note, "method": a.method, "generator_overrides": overrides, "repeat": a.repeat,
            "python": platform.python_version(), "ortools": caps["ortools_version"], "cpu_count": os.cpu_count(),
            "platform": platform.platform(), "specs": f"benchmarks/{a.specs} (see MANIFEST.json; 'specs' is a RECONSTRUCTION of the original benchmark inputs)",
            "started": time.strftime("%Y-%m-%d %H:%M:%S %z")}
    rows = []
    seeds = [int(x) for x in a.seeds.split(",")] if a.seeds else [None]
    meta["seeds"] = seeds if a.seeds else None
    jobs = [(sd, idx, name, raw) for sd in seeds for idx, name, raw in specs]
    for sd, idx, name, raw in jobs:
        for rep in range(a.repeat):
            r = run_case(idx, name, raw, a.method, {**overrides, **({"seed": sd} if sd is not None else {})}); r["rep"] = rep
            r["seed"] = sd if sd is not None else overrides.get("seed", 1); rows.append(r)
            m = r["metrics"] or {}
            print(f"{idx:02d} s{r['seed']} rep{rep} {name[:34]:34} gen={r['generation']:<18} solver={r['solver_status']!s:<10} raw={r['raw_status']!s:<10} "
                  f"val={r['validator']:<5} {r['wall_s']:7.2f}s bbox/rooms={m.get('bbox_over_rooms')} hash={r['layout_hash']}", flush=True)
            out.write_text(json.dumps({"meta": meta, "rows": rows}, indent=1))   # incremental: survives an interrupted run
    meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S %z"); out.write_text(json.dumps({"meta": meta, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
