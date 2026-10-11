"""Heuristic baseline vs CP-SAT on IDENTICAL specs, every layout judged by the independent validator.

Run:  ./.venv/bin/python benchmarks/compare_generators.py [--out benchmarks/results.json]
Nothing here is tuned or selected: the cases are fixed below (random specs use fixed seeds). Times are wall-clock on
whatever machine runs it (this repo's recorded run: see benchmarks/results.json for CPU count and versions).
"""
import argparse, copy, json, os, platform, random, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pharma_layout import cpsat
from pharma_layout.pipeline import run_pipeline

DEMO = json.loads((ROOT / "examples" / "synthetic_osd_demo.json").read_text())


def demo(width=24, **tol):
    d = copy.deepcopy(DEMO); d["building"]["width_m"] = width; d["tolerances"].update(tol); return d


def simple(rooms, adj, W, H):
    return {"building": {"width_m": W, "height_m": H},
            "rooms": [{"id": r[0], "area_m2": r[1], **({"min_dim_m": r[2]} if len(r) > 2 else {})} for r in rooms],
            "adjacency": [{"id": f"ADJ-{i + 1:02d}", "a": a, "b": b} for i, (a, b) in enumerate(adj)]}


def random_case(seed, n, W, H):
    rng = random.Random(seed)
    areas = [round(rng.uniform(6, 45), 1) for _ in range(n)]
    s = min(1.0, 0.7 * W * H / sum(areas)); areas = [max(4.0, round(a * s, 1)) for a in areas]
    rooms = [(f"R{i}", a, round(min(3.0, a ** 0.5 * 0.9), 1)) for i, a in enumerate(areas)]
    pairs = sorted({tuple(sorted(rng.sample(range(n), 2))) for _ in range(n)})
    return simple(rooms, [(f"R{a}", f"R{b}") for a, b in pairs], W, H)


def cases():
    yield "demo 24x16 (chain adjacency)", demo(24)
    yield "demo 30x16", demo(30)
    yield "demo 33x16", demo(33)
    yield "demo 19x16 (tight)", demo(19)
    yield "demo 18x16 (288 m2 < 290.08 m2 minimum)", demo(18)
    yield "demo 24x16, min shared wall 50 m", demo(24, min_shared_edge_m=50)
    ids = "ABCD"
    yield "K4 adjacency on a 2x2 block (impossible)", simple([(i, 25, 5.0) for i in ids], [(a, b) for k, a in enumerate(ids) for b in ids[k + 1:]], 10, 10)
    yield "101 m2 of rooms in 100 m2 (needs -2 % tolerance)", simple([("A", 50.5), ("B", 50.5)], [("A", "B")], 10, 10)
    yield "8.9 m2 room, 3 m min dim (needs +1.1 %)", simple([("A", 8.9, 3.0)], [], 10, 10)
    for n, W, H, seeds in ((8, 24, 16, (1, 2, 3, 4)), (12, 30, 24, (5, 6, 7, 8)), (20, 36, 24, (9, 10, 11, 12)), (30, 30, 24, (13, 14))):
        for sd in seeds:
            yield f"random n={n} {W}x{H} seed={sd}", random_case(sd, n, W, H)


def outcome(res):
    g, v = res["generation"], res["validation"]
    return g["status"], v["overall"], (g.get("solver") or {})


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(ROOT / "benchmarks" / "results.json")); a = ap.parse_args()
    caps = cpsat.capabilities()
    if not caps["cpsat"]:
        sys.exit(caps["reason"])
    rows = []
    print(f"{'case':52} | {'heuristic':28} | {'CP-SAT (grid 0.1 m, 1 worker, 20 s, feasibility)':64}")
    for name, raw in cases():
        h0 = time.perf_counter(); h = run_pipeline(copy.deepcopy(raw), method="heuristic"); ht = time.perf_counter() - h0
        c = run_pipeline(copy.deepcopy(raw), method="cpsat")
        hs, hv, _ = outcome(h); cs, cv, sol = outcome(c)
        row = {"case": name, "heuristic": {"generation": hs, "validator": hv, "seconds": round(ht, 3)},
               "cpsat": {"generation": cs, "validator": cv, "solver_status": sol.get("status"), "raw_status": sol.get("raw_status"),
                         "seconds": sol.get("elapsed_s", 0.0)}}
        rows.append(row)
        hcell = f"{hv if hs == 'placed' else hs}  {ht:5.2f}s"
        ccell = f"gen={cs} solver={sol.get('status')} validator={cv if cs == 'placed' else '-'}  {row['cpsat']['seconds']:6.2f}s"
        print(f"{name:52} | {hcell:28} | {ccell}", flush=True)
    meta = {"python": platform.python_version(), "ortools": caps["ortools_version"], "cpu_count": os.cpu_count(),
            "platform": platform.platform(), "settings": "grid 0.1 m, objective feasibility, num_workers 1, seed 1, time_limit 20 s"}
    Path(a.out).write_text(json.dumps({"meta": meta, "rows": rows}, indent=2))
    ok = lambda k, f: sum(1 for r in rows if f(r[k]))
    print(f"\nvalidator PASS: heuristic {ok('heuristic', lambda x: x['validator'] == 'PASS')}/{len(rows)}, CP-SAT {ok('cpsat', lambda x: x['validator'] == 'PASS' and x['generation'] == 'placed')}/{len(rows)}; wrote {a.out}")


if __name__ == "__main__":
    main()
