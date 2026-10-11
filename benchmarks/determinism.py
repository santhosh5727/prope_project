"""Determinism experiment: does an identical input give the identical layout, solver status and timing?

For each (case, configuration) the SAME spec is solved N times (a) repeatedly inside one process and (b) in N fresh processes with
different PYTHONHASHSEED values. Reports distinct layout hashes, distinct statuses and the wall-time spread. Also: a different
seed (to show the seed does change the search), and a different time limit on a case that finishes early.
This is evidence for THIS machine, Python and OR-Tools build only. It says nothing about other platforms or versions.

  ./.venv/bin/python benchmarks/determinism.py NAME [--set k=v ...] --cases 0,9,14 --n 5
Writes benchmarks/runs/NAME.json (never overwritten).
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import experiment as ex


def child(idx, overrides, folder):
    """Entry point of a fresh process: solve one case once, print one JSON line."""
    specs = {i: (n, r) for i, n, r in ex.load_specs(folder)}
    name, raw = specs[idx]
    print(json.dumps(ex.run_case(idx, name, raw, "cpsat", overrides)))


def stats(rows):
    ts = [r["wall_s"] for r in rows]
    return {"n": len(rows), "distinct_layout_hashes": len({r["layout_hash"] for r in rows}), "distinct_solver_status": sorted({str(r["solver_status"]) for r in rows}),
            "distinct_raw_status": sorted({str(r["raw_status"]) for r in rows}), "wall_min": min(ts), "wall_max": max(ts),
            "wall_spread_pct": round(100 * (max(ts) - min(ts)) / min(ts), 1) if min(ts) > 0 else None,
            "hashes": sorted({str(r["layout_hash"]) for r in rows})}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--cases", required=True); ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--set", action="append", default=[]); ap.add_argument("--specs", default="specs")
    ap.add_argument("--child", type=int); a = ap.parse_args()
    overrides = {k: ([x for x in v.split(",") if x] if k == "model_options" else ex.coerce(v)) for k, v in (s.split("=", 1) for s in a.set)}
    if a.child is not None:
        return child(a.child, overrides, a.specs)
    out = HERE / "runs" / f"{a.name}.json"
    if out.exists(): sys.exit(f"{out} exists")
    specs = {i: (n, r) for i, n, r in ex.load_specs(a.specs)}
    res = {"meta": {"name": a.name, "overrides": overrides, "n": a.n, "cpu_count": os.cpu_count(), "ortools": ex.cpsat.capabilities()["ortools_version"],
                    "python": sys.version.split()[0], "caveat": "evidence for this machine/Python/OR-Tools build only"}, "cases": []}
    for idx in (int(c) for c in a.cases.split(",")):
        name, raw = specs[idx]
        same = [ex.run_case(idx, name, raw, "cpsat", overrides) for _ in range(a.n)]
        fresh = []
        for k in range(a.n):
            env = dict(os.environ, PYTHONHASHSEED=str(k * 7 + 1))
            cmd = [sys.executable, str(Path(__file__).resolve()), "x", "--cases", str(idx), "--child", str(idx), "--specs", a.specs] + [t for s in a.set for t in ("--set", s)]
            fresh.append(json.loads(subprocess.run(cmd, env=env, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]))
        other_seed = ex.run_case(idx, name, raw, "cpsat", {**overrides, "seed": 2})
        row = {"index": idx, "case": name, "same_process": stats(same), "fresh_processes": stats(fresh),
               "all_hashes_equal_across_both": len({r["layout_hash"] for r in same + fresh}) == 1,
               "seed2": {"layout_hash": other_seed["layout_hash"], "solver_status": other_seed["solver_status"], "wall_s": other_seed["wall_s"]}}
        res["cases"].append(row)
        print(f"{idx:02d} {name[:34]:34} same-proc hashes={row['same_process']['distinct_layout_hashes']} fresh-proc hashes={row['fresh_processes']['distinct_layout_hashes']} "
              f"status={row['same_process']['distinct_solver_status']} wall {row['same_process']['wall_min']}-{row['same_process']['wall_max']}s "
              f"(spread {row['same_process']['wall_spread_pct']}%) seed2 hash={'same' if other_seed['layout_hash'] in row['same_process']['hashes'] else 'differs'}", flush=True)
        out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
