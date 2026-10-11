"""Layout alternatives, a transparent score, selection and an indicative cost for the selected design.

Candidates come from the EXISTING generators and options only (baseline heuristic; CP-SAT feasibility; CP-SAT with the compactness
objective). Every layout is judged by the independent validator through ``run_pipeline``. A candidate whose layout is identical to an
earlier one is dropped and reported, never shown as a separate alternative. A candidate that produced no layout (UNKNOWN, infeasible,
error) is listed as "not produced"; UNKNOWN is never described as infeasible.

SCORE (0-100, documented weights; heuristic ranking aid, NOT an engineering or regulatory judgement):
  validity      60 x (passed checks / applicable checks)       the validator's verdict dominates
  compactness   25 x (total placed room area / bounding-box area of the rooms)      1.00 = rooms tile their bounding box
  area accuracy 15 x (1 - mean |area deviation| / area_rel_tol)                    0 deviation = full marks
Ranking: layouts that pass ALL checks rank above any that do not; ties by score.
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor

from . import cost as costmod
from .cpsat import capabilities
from .pipeline import run_pipeline
from .report import _fmt, esc, render_plan_svg

WEIGHTS = {"validity": 60, "compactness": 25, "area accuracy": 15}
CONFIGS = [
    ("A", "Row-packing baseline (heuristic)", {"method": "heuristic"}),
    ("B", "CP-SAT, feasibility", {"method": "cpsat", "objective": "feasibility", "time_limit_s": 10.0}),
    ("C", "CP-SAT, compact (minimise bounding box)", {"method": "cpsat", "objective": "min_bbox_area", "time_limit_s": 14.0,
                                                    "deterministic_time_limit_s": 10.0}),
]


def _layout_key(rooms):
    return tuple(sorted((r["id"], round(r["x"], 2), round(r["y"], 2), round(r["w"], 2), round(r["h"], 2)) for r in rooms))


def _metrics(res):
    spec, g, v = res["spec"], res["generation"], res["validation"]
    n_all = len(spec["rooms"])
    rooms = g["rooms"] if g["status"] == "placed" else []
    out = {"placed": len(rooms), "rooms": n_all, "overall": v["overall"], "summary": v["summary"],
           "failed_rules": [r["rule_id"] for r in v["results"] if r["result"] == "FAIL"]}
    adj = [r for r in v["results"] if r["rule_id"].startswith("V-08:")]
    out["adj_met"], out["adj_total"] = sum(r["result"] == "PASS" for r in adj), len(adj)
    if rooms:
        used = sum(r["w"] * r["h"] for r in rooms)
        x0, y0 = min(r["x"] for r in rooms), min(r["y"] for r in rooms)
        bbox = (max(r["x"] + r["w"] for r in rooms) - x0) * (max(r["y"] + r["h"] for r in rooms) - y0)
        req = {r["id"]: r["area_m2"] for r in spec["rooms"]}
        dev = [abs(r["w"] * r["h"] / req[r["id"]] - 1) for r in rooms if r["id"] in req]
        B = spec["building"]["width_m"] * spec["building"]["height_m"]
        out.update(utilisation=used / B, compactness=used / bbox if bbox else 0.0, mean_dev=sum(dev) / len(dev) if dev else 0.0,
                   bbox_w=max(r["x"] + r["w"] for r in rooms) - x0, bbox_h=max(r["y"] + r["h"] for r in rooms) - y0)
        s = v["summary"]; applicable = s["total"] - s["not_applicable"]
        tol = spec["tolerances"]["area_rel_tol"]
        parts = {"validity": WEIGHTS["validity"] * (s["passed"] / applicable if applicable else 0),
                 "compactness": WEIGHTS["compactness"] * min(1.0, out["compactness"]),
                 "area accuracy": WEIGHTS["area accuracy"] * max(0.0, 1 - out["mean_dev"] / tol)}
        out["score_parts"], out["score"] = parts, sum(parts.values())
    else:
        out["score_parts"], out["score"] = {k: 0.0 for k in WEIGHTS}, 0.0
    return out


def _run(raw, label, gen):
    r = copy.deepcopy(raw)
    r["generator"] = {**gen, "source": "assumption"}
    try:
        res = run_pipeline(r)
    except Exception as e:  # noqa: BLE001 - one failing candidate must not kill the comparison
        return {"label": label, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    g = res["generation"]
    return {"label": label, "res": res, "status": g["status"], "solver": (g.get("solver") or {}).get("status"),
            "elapsed": (g.get("solver") or {}).get("elapsed_s"), "m": _metrics(res), "reason": (g.get("reasons") or [""])[0]}


def build_alternatives(raw: dict) -> dict:
    caps = capabilities()
    configs = [c for c in CONFIGS if c[2]["method"] == "heuristic" or caps["cpsat"]]
    with ThreadPoolExecutor(max_workers=len(configs)) as ex:
        runs = list(ex.map(lambda c: dict(_run(raw, c[1], c[2]), key=c[0]), configs))
    shown, dropped, absent = [], [], []
    seen = {}
    for c in runs:
        if "res" not in c or c["status"] != "placed":
            absent.append(c); continue
        k = _layout_key(c["res"]["generation"]["rooms"])
        if k in seen:
            dropped.append((c, seen[k])); continue
        seen[k] = c["label"]; shown.append(c)
    shown.sort(key=lambda c: (c["m"]["overall"] != "PASS", -c["m"]["score"]))
    for i, c in enumerate(shown, 1):
        c["rank"] = i
    for c in shown:
        c["pros"], c["cons"] = _pros_cons(c, shown)
    sel = shown[0] if shown else None
    return {"shown": shown, "absent": absent, "dropped": dropped, "selected": sel, "caps": caps,
            "cost": costmod.estimate(sel["res"]["spec"], sel["res"]["generation"]["rooms"]) if sel else None,
            "spec": next((c["res"]["spec"] for c in ([sel] if sel else []) + runs if c and "res" in c), None)}


def _pros_cons(c, shown):
    m, pros, cons = c["m"], [], []
    if m["overall"] == "PASS":
        pros.append(f"Passes all {m['summary']['passed']} applicable independent checks")
    else:
        cons.append(f"Fails {m['summary']['failed']} check(s): {', '.join(m['failed_rules'][:6])}")
    best = max(x["m"]["compactness"] for x in shown)
    worst = min(x["m"]["compactness"] for x in shown)
    if len(shown) > 1 and m["compactness"] == best:
        pros.append(f"Most compact: rooms fill {m['compactness']:.1%} of their bounding box")
    elif len(shown) > 1 and m["compactness"] == worst:
        cons.append(f"Least compact: rooms fill only {m['compactness']:.1%} of their bounding box")
    pros.append(f"Adjacency requirements met: {m['adj_met']} of {m['adj_total']}") if m["adj_met"] == m["adj_total"] else cons.append(
        f"Adjacency requirements met: only {m['adj_met']} of {m['adj_total']}")
    if m["mean_dev"] < 0.01:
        pros.append(f"Room areas close to requested (mean deviation {m['mean_dev']:.1%})")
    if c["key"] == "A":
        pros.append("Instant, standard-library only, fully deterministic")
        cons.append("Row packing is not complete: it can fail when a valid layout exists (e.g. the 30 m demo)")
    if c["key"] == "B":
        cons.append("Feasibility only: any valid layout, usually loose (no compactness goal)")
    if c["key"] == "C":
        cons.append("Runs to its limit; compactness is improved, not proven optimal")
    return pros, cons


def _card(c):
    m, res = c["m"], c["res"]
    cls = "pass" if m["overall"] == "PASS" else "fail"
    parts = " + ".join(f"{k} {v:.1f}" for k, v in m["score_parts"].items())
    ul = lambda xs, mark: "".join(f"<li>{mark} {esc(x)}</li>" for x in xs)
    return (f'<div class="panel" style="margin:0"><div class="banner {cls}" style="margin:0 0 8px"><b>#{c["rank"]} {esc(c["label"])}</b> '
            f'&nbsp; score <b>{m["score"]:.1f}</b>/100 &nbsp; validator <b>{esc(m["overall"])}</b></div>'
            + render_plan_svg(res["spec"], res["generation"]["rooms"], res["validation"])
            + f'<p class="note">Rooms placed {m["placed"]}/{m["rooms"]} · checks passed {m["summary"]["passed"]}/{m["summary"]["total"] - m["summary"]["not_applicable"]}, '
              f'failed {m["summary"]["failed"]} · space utilisation {m["utilisation"]:.1%} of building · rooms fill {m["compactness"]:.1%} of their bounding box '
              f'({m["bbox_w"]:.1f} x {m["bbox_h"]:.1f} m) · score = {esc(parts)}</p>'
            f'<ul style="margin:4px 0;padding-left:18px;list-style:none">{ul(c["pros"], "+")}{ul(c["cons"], "&minus;")}</ul></div>')


def _money(x): return f"{x:,.0f}"


def render_alternatives(a: dict) -> str:
    spec = a["spec"]
    if spec is None:
        return '<div class="errors">No candidate could be run.</div>'
    steps = ["Facility brief", "Generate alternatives", "Compare and select", "Validate", "Estimate cost", "View report"]
    p = ['<div class="rep" id="altrep">',
         '<p style="margin:0 0 10px">' + " &rarr; ".join(f'<span class="tag" style="font-size:12px">{i + 1}. {s} &#10003;</span>' for i, s in enumerate(steps)) + "</p>"]
    n_adj = len(spec["adjacency"])
    p.append(f'<h3>1. Facility brief</h3><p class="note">{esc(spec["meta"]["title"])} - building {spec["building"]["width_m"]:g} x {spec["building"]["height_m"]:g} m, '
             f'{len(spec["rooms"])} rooms, {n_adj} adjacency requirements, area tolerance &plusmn;{spec["tolerances"]["area_rel_tol"] * 100:g} %. '
             f'All values are synthetic demonstration inputs. Input is a structured form: <b>no AI / LLM is connected</b> (natural-language brief intake is future work).</p>')
    p.append("<h3>2. Layout alternatives (existing generators and options only)</h3>")
    if a["shown"]:
        p.append('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:12px">' + "".join(_card(c) for c in a["shown"]) + "</div>")
    for c, same in a["dropped"]:
        p.append(f'<p class="note">Not shown as a separate alternative: <b>{esc(c["label"])}</b> returned the identical layout to <b>{esc(same)}</b>.</p>')
    for c in a["absent"]:
        why = c.get("error") or (f'{c["status"]}' + (f' / solver {c["solver"]}' if c.get("solver") else ""))
        extra = " This is NOT a claim of infeasibility." if c.get("status") == "unknown" else ""
        p.append(f'<div class="warnbox">No layout produced by <b>{esc(c["label"])}</b>: {esc(why)}. {esc(c.get("reason", ""))[:220]}{extra}</div>')
    if len(a["shown"]) < 3:
        p.append(f'<p class="note">Only {len(a["shown"])} genuine candidate(s) available; none is duplicated to fill the gap.</p>')
    if a["shown"]:
        rows = "".join(f'<tr><td>#{c["rank"]}</td><td>{esc(c["label"])}</td><td>{c["m"]["placed"]}/{c["m"]["rooms"]}</td>'
                       f'<td><span class="res {"PASS" if c["m"]["overall"] == "PASS" else "FAIL"}">{esc(c["m"]["overall"])}</span> '
                       f'({c["m"]["summary"]["failed"]} failed)</td><td>{c["m"]["utilisation"]:.1%}</td><td>{c["m"]["compactness"]:.1%}</td>'
                       f'<td>{c["m"]["adj_met"]}/{c["m"]["adj_total"]}</td><td><b>{c["m"]["score"]:.1f}</b></td></tr>' for c in a["shown"])
        p.append("<h3>3. Comparison and selection</h3>"
                 '<div class="scroll"><table><thead><tr><th>Rank</th><th>Alternative</th><th>Rooms placed</th><th>Independent validation</th>'
                 '<th>Utilisation (rooms / building)</th><th>Compactness (rooms / bbox)</th><th>Adjacency met</th><th>Score</th></tr></thead><tbody>' + rows + "</tbody></table></div>"
                 f'<p class="note"><b>Score weights (documented, simple):</b> validity {WEIGHTS["validity"]} (passed / applicable checks) + compactness {WEIGHTS["compactness"]} '
                 f'(room area / bounding-box area) + area accuracy {WEIGHTS["area accuracy"]} (1 - mean area deviation / tolerance). Layouts passing every check rank above any that do not. '
                 'This is a ranking aid, not an engineering or regulatory judgement.</p>')
        s = a["selected"]
        why = f'It ranks first with {s["m"]["score"]:.1f}/100'
        if len(a["shown"]) > 1:
            o = a["shown"][1]; why += f' (next: {esc(o["label"])}, {o["m"]["score"]:.1f}; {"validator " + o["m"]["overall"] if o["m"]["overall"] != s["m"]["overall"] else "the margin comes from compactness / area accuracy"})'
        p.append(f'<div class="banner {"pass" if s["m"]["overall"] == "PASS" else "fail"}"><b>Selected: {esc(s["label"])}.</b> {why}. '
                 f'Validator: {esc(s["m"]["overall"])} ({s["m"]["summary"]["passed"]} passed, {s["m"]["summary"]["failed"]} failed). Selection is a recommendation to review, not an approval.</div>')
        p.append("<h3>5. Indicative Total Investment Cost - selected design</h3>" + _cost_html(a["cost"]))
        p.append("<h3>4 and 6. Validation, traceability and report for the selected design</h3>"
                 '<p class="note">Geometric and input checks only (internal checks of this tool); no regulatory verification has been performed. '
                 'Warnings: the validator has no warning level; checks that do not apply are shown as N/A.</p>' + s["res"]["html"])
    p.append('<p class="note">Visualisation is a <b>conceptual 2D plan</b>, not an IFC / BIM model. Equipment layout and material / personnel flows are not '
             'represented because the data does not contain them; the dashed / solid lines show adjacency requirements only.</p></div>')
    return "".join(p)


def _cost_html(c):
    t = c["total"]
    rows = "".join(f'<tr><td>{esc(l["component"])}</td><td>{esc(str(l["quantity"]))} {esc(l["unit"])}</td><td>{esc(str(l["rate"]))}</td><td class="note">{esc(l["formula"])}</td>'
                   f'<td style="text-align:right">{_money(l["low"])}</td><td style="text-align:right"><b>{_money(l["base"])}</b></td><td style="text-align:right">{_money(l["high"])}</td></tr>'
                   for l in c["lines"])
    drv = "; ".join(f"{esc(n)} {s:.0%}" for n, s in c["drivers"])
    return (f'<div class="warnbox"><b>ILLUSTRATIVE ONLY.</b> {esc(c["label"])} Currency: {esc(c["currency"])}.</div>'
            f'<p><b>Indicative TIC: {_money(t["base"])}</b> (low {_money(t["low"])} &ndash; high {_money(t["high"])}); about {_money(c["per_m2_base"])} per m&sup2; of placed room area. '
            f'Major cost drivers: {drv}.</p>'
            '<div class="scroll"><table><thead><tr><th>Component</th><th>Quantity</th><th>Rate (synthetic)</th><th>Formula</th><th>Low</th><th>Base</th><th>High</th></tr></thead><tbody>'
            + rows + f'<tr><td><b>Total</b></td><td></td><td></td><td></td><td style="text-align:right"><b>{_money(t["low"])}</b></td><td style="text-align:right"><b>{_money(t["base"])}</b></td>'
            f'<td style="text-align:right"><b>{_money(t["high"])}</b></td></tr></tbody></table></div>'
            '<p class="note"><b>Assumptions:</b> ' + esc("; ".join(c["assumptions"])) + '.</p><p class="note"><b>Exclusions:</b> ' + esc("; ".join(c["exclusions"])) + ".</p>")
