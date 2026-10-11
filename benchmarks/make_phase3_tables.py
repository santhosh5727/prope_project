"""Print the Phase-3 summary tables (markdown) computed from benchmarks/runs/*.json. Nothing here is typed in by hand."""
import json, statistics
from pathlib import Path

R = Path(__file__).resolve().parent / "runs"
load = lambda n: json.loads((R / f"{n}.json").read_text())
rows = lambda n: load(n)["rows"]
ok = lambda r: r["generation"] == "placed" and r["validator"] == "PASS"


def e8(tag, cfg):
    rs = rows(f"e8_{tag}_{cfg}"); n = len(rs)
    p = [r for r in rs if ok(r)]
    f = [r for r in rs if r["generation"] == "placed" and r["validator"] != "PASS"]
    u = [r for r in rs if r["generation"] == "unknown"]; i = [r for r in rs if r["generation"] in ("infeasible", "infeasible_on_grid")]
    med = lambda xs: f"{statistics.median(xs):.2f}" if xs else "-"
    return n, len(p), len(f), len(u), len(i), med([r["wall_s"] for r in p]), med([r["metrics"]["bbox_over_rooms"] for r in p]), sum(r["wall_s"] for r in rs)


print("### Heuristic vs CP-SAT on the same specs (validator is the judge)\n")
print("| specs | method | specs | validator PASS | placed but FAIL | UNKNOWN | proven infeasible* | median s (solved) | median bbox / room area (solved) | total s |")
print("|---|---|---|---|---|---|---|---|---|---|")
names = {"heuristic": "baseline heuristic", "A_base": "CP-SAT A: default (feasibility)", "B_core_first": "CP-SAT B: A + core_first",
         "C_core_first_bbox_area": "CP-SAT C: B + min_bbox_area", "D_bbox_area": "CP-SAT D: min_bbox_area only"}
for tag, label in (("saved", "23 saved (reconstructed)"), ("holdout", "14 held-out")):
    for cfg, nm in names.items():
        if not (R / f"e8_{tag}_{cfg}.json").exists(): continue
        n, p, f, u, i, ms, mb, tot = e8(tag, cfg)
        print(f"| {label} | {nm} | {n} | {p} | {f} | {u} | {i} | {ms} | {mb} | {tot:.0f} |")
print("\n*pre-check (continuous space) or on the 0.1 m grid; see the status semantics in the README.\n")

print("### E2: five seeds, 4 UNKNOWN cases + 3 guard cases (solved = validator PASS within 20 s)\n")
print("| case | " + " | ".join(["base", "mirror_symmetry", "cumulative_cuts", "linear_adjacency"]) + " |\n|---|---|---|---|---|")
cfgs = ["e2_base", "e2_mirror_symmetry", "e2_cumulative_cuts", "e2_linear_adjacency"]
data = {c: rows(c) for c in cfgs}
for idx in (15, 17, 18, 19, 20, 21, 22):
    cells = []
    for c in cfgs:
        rs = [r for r in data[c] if r["index"] == idx]; s = [r for r in rs if ok(r)]
        cells.append(f"{len(s)}/{len(rs)}" + (f" (median {statistics.median(r['wall_s'] for r in s):.1f} s)" if s else ""))
    print(f"| {idx} | " + " | ".join(cells) + " |")
print("| **all** | " + " | ".join(f"**{sum(ok(r) for r in data[c])}/{len(data[c])}**" for c in cfgs) + " |")
