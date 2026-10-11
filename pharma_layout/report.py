"""Render the explainable report (HTML fragment + SVG plan).

Every string that originates from user input is passed through ``html.escape``.
The report keeps four kinds of statements visibly separate:
  1. user-provided inputs            (source tag "user")
  2. synthetic demonstration values  (source tag "synthetic_demo")
     and modelling assumptions       (source tag "assumption")
  3. implemented geometric checks    (rule table, V-xx)
  4. unimplemented requirements      (out-of-scope table, OOS-xx)
"""
from __future__ import annotations

from html import escape as esc

from .spec import gen_source, tol_source

SOURCE_LABEL = {
    "user": "user-provided",
    "synthetic_demo": "synthetic demo",
    "assumption": "assumption",
    "spec": "from spec",
    "rooms": "from spec",
    "layout": "from layout",
}

# Deliberately generic: no clause numbers or standards are cited because none
# have been verified AND implemented in this slice.
OUT_OF_SCOPE = [
    ("OOS-01", "Regulatory / GMP compliance of any kind",
     "No regulatory requirement is encoded or verified. A PASS below is not a compliance statement."),
    ("OOS-02", "Material, personnel, waste and equipment flow separation; route checks",
     "Rooms are rectangles with adjacency only; no flow graphs or door/route model exists."),
    ("OOS-03", "Cleanliness zoning, pressure cascades, airlock logic",
     "No zone or pressure attributes are modelled."),
    ("OOS-04", "Equipment footprints, clearances, maintainability",
     "Equipment is not represented in this slice."),
    ("OOS-05", "Fire, egress and occupational-safety distances; local building codes",
     "Not modelled. Requires jurisdiction-specific, expert-verified rules."),
    ("OOS-06", "HVAC, utilities, structure",
     "Not modelled."),
    ("OOS-07", "IFC / BIM export and cost estimation",
     "Deliberately excluded from this first slice."),
]

CSS = """
:root{--bg:#fff;--fg:#1c2330;--muted:#5b6678;--line:#d5dae3;--card:#f6f8fb;--ok:#1e7a46;--okbg:#e5f4ea;
--bad:#b3261e;--badbg:#fbe7e5;--warn:#8a5a00;--warnbg:#fff3d6;--acc:#2456c8;--room:#e8eefb;--roombad:#fbd9d5}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e9ef;--muted:#9aa5b8;--line:#2f3744;--card:#1c2129;
--ok:#59c387;--okbg:#17301f;--bad:#ff8b82;--badbg:#3a1b19;--warn:#f0c15a;--warnbg:#3a2e12;--acc:#8fb0ff;--room:#223052;--roombad:#5a2824}}
.rep{color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.rep h3{margin:22px 0 8px;font-size:15px}
.banner{border-radius:8px;padding:10px 14px;margin:0 0 10px;border:1px solid var(--line)}
.banner.pass{background:var(--okbg);border-color:var(--ok)}.banner.fail{background:var(--badbg);border-color:var(--bad)}
.banner.warn{background:var(--warnbg);border-color:var(--warn)}
.banner b{font-size:15px}.note{color:var(--muted);font-size:13px}
.warnbox{background:var(--warnbg);border:1px solid var(--warn);border-radius:8px;padding:8px 12px;margin:8px 0;color:var(--fg)}
.rep table{border-collapse:collapse;width:100%;font-size:13px}
.rep th,.rep td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
.rep th{background:var(--card);position:sticky;top:0}
.tag{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 7px;font-size:11px;color:var(--muted);white-space:nowrap}
.tag.user{border-color:var(--acc);color:var(--acc)}
.res{font-weight:700;white-space:nowrap}.res.PASS{color:var(--ok)}.res.FAIL{color:var(--bad)}.res.NA{color:var(--muted)}
.plan{width:100%;height:auto;border:1px solid var(--line);border-radius:8px;background:var(--bg)}
.plan .bld{fill:none;stroke:var(--fg);stroke-width:2}.plan .free{fill:var(--card)}
.plan .room{fill:var(--room);fill-opacity:.85;stroke:var(--fg);stroke-width:1}
.plan .room.bad{fill:var(--roombad);stroke:var(--bad);stroke-width:2}
.plan text{fill:var(--fg);font:11px system-ui,sans-serif;pointer-events:none;paint-order:stroke;stroke:var(--bg);stroke-width:3px;stroke-opacity:.75;stroke-linejoin:round}
.plan .adj{stroke-width:2.5;fill:none}.plan .adj.ok{stroke:var(--ok)}.plan .adj.bad{stroke:var(--bad);stroke-dasharray:6 4}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:6px 0}
.legend i{display:inline-block;width:22px;height:0;border-top:3px solid;vertical-align:middle;margin-right:5px}
.legend i.ok{border-color:var(--ok)}.legend i.bad{border-color:var(--bad);border-top-style:dashed}
.scroll{overflow-x:auto}
"""


def _fmt(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}"


def _tag(source: str) -> str:
    cls = "tag user" if source == "user" else "tag"
    return f'<span class="{cls}">{esc(SOURCE_LABEL.get(source, source))}</span>'


def render_plan_svg(spec: dict, placed: list[dict], validation: dict) -> str:
    W, H = spec["building"]["width_m"], spec["building"]["height_m"]
    pad = 20
    s = min(880 / W, 520 / H)
    vw, vh = W * s + 2 * pad, H * s + 2 * pad
    bad_rooms = set(validation["per_room_failures"])
    by_id = {p["id"]: p for p in placed}
    names = {r["id"]: r["name"] for r in spec["rooms"]}
    req = {r["id"]: r["area_m2"] for r in spec["rooms"]}

    def X(v): return pad + v * s
    out = [f'<svg class="plan" viewBox="0 0 {_fmt(vw, 1)} {_fmt(vh, 1)}" role="img" '
           f'aria-label="2D plan of {len(placed)} rooms in a {W:g} by {H:g} metre building">',
           f'<rect class="free" x="{pad}" y="{pad}" width="{_fmt(W * s)}" height="{_fmt(H * s)}"/>']
    for r in spec["rooms"]:
        p = by_id.get(r["id"])
        if not p:
            continue
        x, y, w, h = X(p["x"]), X(p["y"]), p["w"] * s, p["h"] * s
        bad = r["id"] in bad_rooms
        area = p["w"] * p["h"]
        tip = (f'{r["id"]} - {r["name"]}: {p["w"]:.2f} x {p["h"]:.2f} m = {area:.2f} m2 '
               f'(required {req[r["id"]]:g} m2)' + (f' | FAILS {", ".join(validation["per_room_failures"][r["id"]])}' if bad else ""))
        out.append(f'<g><title>{esc(tip)}</title>'
                   f'<rect class="room{" bad" if bad else ""}" x="{_fmt(x)}" y="{_fmt(y)}" '
                   f'width="{_fmt(max(w, 0))}" height="{_fmt(max(h, 0))}"/>')
        maxc = int((w - 8) / 6.2)
        label = r["name"] if len(r["name"]) <= maxc else r["id"]
        if len(label) > maxc:
            label = (label[:maxc - 1] + "…") if maxc >= 3 else ""
        lines = [label] if label else []
        if w >= 60 and h >= 34:
            lines.append(f'{p["w"]:.1f} x {p["h"]:.1f} m')
        if w >= 60 and h >= 50:
            lines.append(f'{area:.1f} m²')
        # Labels sit at the top of the room so the centre-to-centre adjacency lines do not strike through them.
        lines = lines[:max(1, int((h - 6) / 13))]
        for i, ln in enumerate(lines):
            out.append(f'<text x="{_fmt(x + w / 2)}" y="{_fmt(y + 15 + i * 13)}" text-anchor="middle">{esc(ln)}</text>')
        out.append("</g>")
    for res in validation["results"]:
        if "pair" not in res:
            continue
        a, b = (by_id.get(i) for i in res["pair"])
        if not a or not b:
            continue
        ax, ay = X(a["x"] + a["w"] / 2), X(a["y"] + a["h"] / 2)
        bx, by = X(b["x"] + b["w"] / 2), X(b["y"] + b["h"] / 2)
        cls = "ok" if res["satisfied"] else "bad"
        out.append(f'<g><title>{esc(res["rule_id"] + ": " + res["explanation"])}</title>'
                   f'<line class="adj {cls}" x1="{_fmt(ax)}" y1="{_fmt(ay)}" x2="{_fmt(bx)}" y2="{_fmt(by)}"/></g>')
    out.append(f'<rect class="bld" x="{pad}" y="{pad}" width="{_fmt(W * s)}" height="{_fmt(H * s)}" fill="none"/>')
    out.append("</svg>")
    return "".join(out)


def _room_table(spec, placed, validation) -> str:
    by_id = {p["id"]: p for p in placed}
    fails = validation["per_room_failures"]
    rows = []
    for r in spec["rooms"]:
        p = by_id.get(r["id"])
        if p:
            area = p["w"] * p["h"]
            dev = (area - r["area_m2"]) / r["area_m2"] * 100
            dims, got, devs = f'{_fmt(p["w"])} x {_fmt(p["h"])}', _fmt(area), ("0.0 %" if abs(dev) < 0.05 else f"{dev:+.1f} %")
        else:
            dims = got = devs = "not placed"
        md = "-" if r["min_dim_m"] is None else f'{r["min_dim_m"]:g}'
        status = ('<span class="res FAIL">FAIL ' + esc(", ".join(fails[r["id"]])) + "</span>") if r["id"] in fails \
            else '<span class="res PASS">OK</span>'
        rows.append(f'<tr><td>{esc(r["id"])}</td><td>{esc(r["name"])}</td><td>{r["area_m2"]:g}</td>'
                    f'<td>{md}</td><td>{dims}</td><td>{got}</td><td>{devs}</td><td>{status}</td><td>{_tag(r["source"])}</td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>ID</th><th>Name</th><th>Required m²</th><th>Min dim m</th>'
            '<th>Placed w x h (m)</th><th>Placed m²</th><th>Area dev.</th><th>Checks</th><th>Input source</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>")


def _trace_table(validation) -> str:
    """Compact requirement -> check -> evidence view, derived only from the validator's results (no new data, no new claims)."""
    gap = {"synthetic_demo": "demo value, no external source", "assumption": "modelling assumption, not sourced",
           "user": "typed by the user, not verified by this tool"}
    rows, counts = [], {}
    for r in validation["results"]:
        srcs = sorted({i["source"] for i in r["inputs"] if i["source"] in gap})
        counts[r["result"]] = counts.get(r["result"], 0) + 1
        prov = " ".join(_tag(x) for x in srcs) or '<span class="note">derived from spec / layout</span>'
        ev = "; ".join(gap[x] for x in srcs) or "none beyond the inputs above"
        vals = "; ".join(f'{esc(i["name"])} = {esc(str(i["value"]))}' for i in r["inputs"][:3]) or "-"
        cls = "NA" if r["result"] == "N/A" else r["result"]
        rows.append(f'<tr><td style="white-space:nowrap"><b>{esc(r["rule_id"])}</b></td><td>{esc(r["title"])}<br><span class="note">{vals}</span></td>'
                    f'<td>{prov}</td><td><span class="res {cls}">{esc(r["result"])}</span><br><span class="note">{esc(r["explanation"])}</span></td>'
                    f'<td class="note">{esc(ev)}</td></tr>')
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    return (f'<p class="note">{len(validation["results"])} implemented geometric checks ({esc(summary)}). '
            '<b>Verified external sources used: 0</b> - every value is a synthetic demo value, a modelling assumption or user input, '
            'and none is checked against a regulation or standard. A PASS means the geometry satisfies these stated inputs only; '
            'it is not GMP or regulatory compliance.</p>'
            '<div class="scroll"><table><thead><tr><th>ID</th><th>Requirement (value)</th><th>Provenance</th><th>Status and explanation</th>'
            '<th>Missing evidence</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def _rule_table(validation) -> str:
    rows = []
    for r in validation["results"]:
        inputs = "<br>".join(f'{esc(i["name"])}: {esc(str(i["value"]))} {_tag(i["source"])}' for i in r["inputs"]) or "-"
        cls = "NA" if r["result"] == "N/A" else r["result"]
        rows.append(f'<tr><td style="white-space:nowrap"><b>{esc(r["rule_id"])}</b></td><td><b>{esc(r["title"])}</b><br>'
                    f'<span class="note">{esc(r["description"])}</span></td><td>{inputs}</td>'
                    f'<td><span class="res {cls}">{esc(r["result"])}</span></td><td>{esc(r["explanation"])}</td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>Rule ID</th><th>Description (implemented geometric check)</th>'
            '<th>Input / assumption used</th><th>Result</th><th>Explanation</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>")


def _inputs_table(spec) -> str:
    b, t = spec["building"], spec["tolerances"]
    rows = [
        ("building width x height", f'{b["width_m"]:g} x {b["height_m"]:g} m', b["source"]),
        ("area_rel_tol", f'{t["area_rel_tol"] * 100:g} % of required area', tol_source(spec, "area_rel_tol")),
        ("min_shared_edge_m", f'{t["min_shared_edge_m"]:g} m (adjacency definition)', tol_source(spec, "min_shared_edge_m")),
        ("geom_eps_m", f'{t["geom_eps_m"]:g} m (numerical tolerance)', tol_source(spec, "geom_eps_m")),
    ]
    gcfg = spec["generator"]
    rows.append(("generator method", gcfg["method"], gen_source(spec, "method")))
    if gcfg["method"] == "cpsat":
        rows += [("generator grid_m", f'{gcfg["grid_m"]:g} m (CP-SAT integer grid)', gen_source(spec, "grid_m")),
                 ("generator objective", gcfg["objective"], gen_source(spec, "objective")),
                 ("generator time_limit_s", f'{gcfg["time_limit_s"]:g} s', gen_source(spec, "time_limit_s")),
                 ("generator num_workers / seed", f'{gcfg["num_workers"]} / {gcfg["seed"]}', gen_source(spec, "num_workers"))]
        if gcfg.get("deterministic_time_limit_s") is not None:
            rows.append(("generator deterministic_time_limit_s", f'{gcfg["deterministic_time_limit_s"]:g} (work-based limit)', gen_source(spec, "deterministic_time_limit_s")))
        if gcfg.get("model_options"):
            rows.append(("generator model_options", ", ".join(gcfg["model_options"]), gen_source(spec, "model_options")))
    rows += [(f'adjacency {a["id"]}', f'{a["a"]} - {a["b"]}', a["source"]) for a in spec["adjacency"]]
    body = "".join(f"<tr><td>{esc(n)}</td><td>{esc(v)}</td><td>{_tag(s)}</td></tr>" for n, v, s in rows)
    return ('<div class="scroll"><table><thead><tr><th>Input</th><th>Value</th><th>Source</th></tr></thead><tbody>'
            + body + "</tbody></table></div>")


def render_report(spec: dict, generation: dict, validation: dict, notes: list[str] | None = None) -> str:
    s = validation["summary"]
    parts = ['<div class="rep">']
    st, sol = generation["status"], generation.get("solver")
    if st == "infeasible":
        parts.append('<div class="banner fail"><b>No layout produced: the inputs are infeasible.</b><br>'
                     + "<br>".join(esc(r) for r in generation["reasons"])
                     + f' <span class="note">({esc(generation.get("infeasibility_scope", "continuous space"))})</span></div>')
    elif st == "infeasible_on_grid":
        parts.append('<div class="banner fail"><b>No layout produced: infeasible for the grid model only.</b><br>'
                     + "<br>".join(esc(r) for r in generation["reasons"]) + "</div>")
    elif st == "unknown":
        parts.append('<div class="banner warn"><b>No conclusion: the solver stopped without a layout (UNKNOWN).</b><br>'
                     + "<br>".join(esc(r) for r in generation["reasons"]) + "</div>")
    elif st == "error":
        parts.append('<div class="banner fail"><b>Generator error (MODEL_INVALID): nothing was generated.</b><br>'
                     + "<br>".join(esc(r) for r in generation["reasons"]) + "</div>")
    if validation["overall"] == "PASS":
        parts.append(f'<div class="banner pass"><b>All {s["total"] - s["not_applicable"]} encoded checks passed.</b> '
                     f'<span class="note">Geometric and input checks on the inputs below only; this is not a regulatory or GMP compliance statement.</span></div>')
    else:
        parts.append(f'<div class="banner fail"><b>{s["failed"]} of {s["total"]} encoded checks failed.</b> '
                     f'<span class="note">Failed rooms are outlined in red; unmet adjacencies are red dashed lines. '
                     f'Passing checks would still not be a compliance statement.</span></div>')
    m = generation["method"]
    if sol:
        bits = [f'CP-SAT (OR-Tools {esc(str(sol.get("ortools_version", "?")))})' if sol.get("ortools_version") else "CP-SAT",
                f'grid {sol["grid_m"]:g} m',
                f'objective {esc(str(sol.get("objective", "-")))}',
                f'solver status <b>{esc(str(sol["status"]))}</b> (OR-Tools: {esc(str(sol.get("raw_status")))}) in {sol["elapsed_s"]:.2f} s']
        if sol.get("objective_value") is not None:
            bits.append(f'objective value {sol["objective_value"]:g} (bound {sol["best_objective_bound"]:g}) in grid units')
        if sol.get("model_options"):
            bits.append("options " + esc(", ".join(sol["model_options"])))
        if sol.get("core"):
            c = sol["core"]
            bits.append(f'relaxation on {c["rooms"]} rooms with adjacency: {esc(str(c["status"]))} in {c["seconds"]:.2f} s')
        if st == "placed":
            bits.append(f'unallocated building area {_fmt(generation["unallocated_area_m2"])} m²')
        line = "Generator: " + "; ".join(bits) + ". "
        if sol.get("approximations"):
            line += "Grid approximations: " + esc("; ".join(sol["approximations"])) + ". "
        line += ("The solver result is only a candidate; INFEASIBLE refers to the discretised model, "
                 "and the validator below is authoritative.")
        parts.append(f'<p class="note">{line}</p>')
    elif st == "placed":
        sr = generation["self_report"]
        parts.append(
            f'<p class="note">Generator: {esc(m["name"])}, {m["rows"]} row(s){", serpentine" if m["serpentine"] else ""}; '
            f'{m["candidates_evaluated"]} candidates evaluated{" (search capped, result may not be the best)" if m["search_truncated"] else ""}. '
            f'Unallocated building area: {_fmt(generation["unallocated_area_m2"])} m². '
            f'Generator self-report is advisory; the validator below is authoritative.'
            + (' This baseline heuristic could not produce a layout that passes; that does NOT show that no valid layout exists '
               '(try the cpsat method).' if validation["overall"] != "PASS" else "") + '</p>')
    for n in notes or []:
        parts.append(f'<div class="warnbox">{esc(n)}</div>')
    parts.append("<h3>2D plan</h3>" + render_plan_svg(spec, generation["rooms"], validation))
    parts.append('<div class="legend"><span><i class="ok"></i>adjacency met</span>'
                 '<span><i class="bad"></i>adjacency NOT met</span>'
                 '<span>red outline = room fails at least one check · hover a room or line for detail</span></div>')
    parts.append("<h3>Rooms</h3>" + _room_table(spec, generation["rooms"], validation))
    parts.append("<h3>Traceability: requirement to check to evidence</h3>" + _trace_table(validation))
    parts.append("<h3>Validation rules (implemented geometric checks)</h3>" + _rule_table(validation))
    parts.append("<h3>Inputs and assumptions</h3>"
                 '<p class="note">Tags: <span class="tag user">user-provided</span> entered or edited by you · '
                 '<span class="tag">synthetic demo</span> invented demonstration value, not an engineering standard · '
                 '<span class="tag">assumption</span> modelling choice of this software.</p>' + _inputs_table(spec))
    parts.append("<h3>Not implemented (out of scope for this slice)</h3>"
                 '<p class="note">None of these is checked, and none is claimed. No regulation clauses or standards are cited '
                 'because none were verified and implemented here.</p>'
                 '<div class="scroll"><table><thead><tr><th>ID</th><th>Requirement area</th><th>Status</th></tr></thead><tbody>'
                 + "".join(f'<tr><td>{i}</td><td>{esc(t)}</td><td><span class="res NA">NOT IMPLEMENTED</span> - {esc(d)}</td></tr>'
                           for i, t, d in OUT_OF_SCOPE) + "</tbody></table></div>")
    parts.append("</div>")
    return "".join(parts)


def standalone_page(title: str, fragment: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)}</title><style>body{{margin:0;padding:16px;background:var(--bg);color:var(--fg)}}{CSS}</style></head>"
            f"<body><h2 class=\"rep\">{esc(title)}</h2>{fragment}</body></html>")
