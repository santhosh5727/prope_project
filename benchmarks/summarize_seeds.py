"""Multi-seed table: for each case and run file, 'solved/seeds' and the median wall time of the solved runs.
  ./.venv/bin/python benchmarks/summarize_seeds.py runA runB ...
"solved" = generation placed AND the independent validator says PASS. Medians are over solved runs only (shown as -- if none)."""
import json, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
names = sys.argv[1:]
runs = {n: json.loads((HERE / "runs" / f"{n}.json").read_text())["rows"] for n in names}
cases = sorted({(r["index"], r["case"]) for rows in runs.values() for r in rows})
print(f"{'case':42}" + "".join(f"{n[-20:]:>22}" for n in names))
tot = {n: [0, 0] for n in names}
for idx, case in cases:
    line = f"{idx:03d} {case[:37]:38}"
    for n in names:
        rs = [r for r in runs[n] if r["index"] == idx]
        ok = [r for r in rs if r["generation"] == "placed" and r["validator"] == "PASS"]
        tot[n][0] += len(ok); tot[n][1] += len(rs)
        med = f"{statistics.median(r['wall_s'] for r in ok):.1f}s" if ok else "--"
        line += f"{f'{len(ok)}/{len(rs)}  med {med}':>22}" if rs else f"{'-':>22}"
    print(line)
print(f"{'ALL':42}" + "".join(f"{f'{t[0]}/{t[1]}':>22}" for t in tot.values()))
bad = [(n, r["index"], r["seed"]) for n, rows in runs.items() for r in rows if r["generation"] == "placed" and r["validator"] != "PASS"]
print("placed-but-validator-FAIL runs:", bad or "none")
