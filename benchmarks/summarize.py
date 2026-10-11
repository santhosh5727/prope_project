"""Print a side-by-side table of benchmarks/runs/<name>.json files (rows = cases, columns = runs).

  ./.venv/bin/python benchmarks/summarize.py e1_base e1_tight_domains ...   [--metric wall|bbox]
Cell = status letter + wall seconds:  P = placed & validator PASS, F = placed & validator FAIL, U = UNKNOWN, I = infeasible (pre-check or
grid), E = error.  Runs are only ever compared on the cases they share; nothing here is an average over a hand-picked subset.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def letter(r):
    g = r["generation"]
    if g == "placed": return "P" if r["validator"] == "PASS" else "F"
    return {"unknown": "U", "infeasible": "I", "infeasible_on_grid": "I", "error": "E"}.get(g, "?")


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    metric = "bbox" if "--metric" in sys.argv and sys.argv[sys.argv.index("--metric") + 1] == "bbox" else "wall"
    runs = {n: json.loads((HERE / "runs" / f"{n}.json").read_text()) for n in names}
    cases = sorted({(r["index"], r["case"]) for d in runs.values() for r in d["rows"]})
    print(f"{'case':44}" + "".join(f"{n[-17:]:>18}" for n in names))
    for idx, case in cases:
        line = f"{idx:02d} {case[:40]:41}"
        for n in names:
            rs = [r for r in runs[n]["rows"] if r["index"] == idx]
            if not rs: line += f"{'-':>18}"; continue
            r = rs[0]
            val = r["wall_s"] if metric == "wall" else (r["metrics"] or {}).get("bbox_over_rooms")
            line += f"{letter(r) + ' ' + (f'{val:.2f}' if isinstance(val, (int, float)) else '-'):>18}"
        print(line)
    print("solved (P):  " + "  ".join(f"{n[-17:]}={sum(1 for r in d['rows'] if letter(r) == 'P')}/{len(d['rows'])}" for n, d in runs.items()))


main()
