"""CLI:  python3 -m pharma_layout serve | run SPEC [--method heuristic|cpsat] [--out report.html] [--json result.json]

Exit codes of ``run``:  0 all checks pass | 1 validation failed (includes infeasible / unknown generator outcomes)
                        | 2 unreadable or invalid input | 3 internal error (a bug; never a verdict on the layout)"""
from __future__ import annotations

import argparse
import json
import sys

from .pipeline import run_pipeline
from .report import standalone_page
from .server import EXAMPLE_PATH, serve
from .spec import SpecError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pharma_layout", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    r = sub.add_parser("run", help="generate + validate one spec from the command line")
    r.add_argument("spec", nargs="?", default=str(EXAMPLE_PATH))
    r.add_argument("--method", choices=["heuristic", "cpsat"], help="override spec.generator.method (default: spec value, else heuristic)")
    r.add_argument("--out", help="write standalone HTML report here")
    r.add_argument("--json", dest="json_out", help="write full result JSON here")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        serve(a.host, a.port)
        return 0

    try:
        with open(a.spec, encoding="utf-8") as f:
            raw = json.load(f)
    except RecursionError:
        print("cannot read spec: JSON nesting is too deep", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:   # includes JSONDecodeError, UnicodeDecodeError, integer-size limit
        print(f"cannot read spec: {str(e)[:200]}", file=sys.stderr)
        return 2
    try:
        res = run_pipeline(raw, method=a.method)
    except SpecError as e:
        print("INVALID SPEC:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"INTERNAL ERROR ({type(e).__name__}: {str(e)[:200]}). This is a bug, not a verdict on the layout.", file=sys.stderr)
        return 3

    v = res["validation"]
    g = res["generation"]
    print(f"generator: {g['method']['name']} | status: {g['status']}" + (
        f" | solver {g['solver']['status']} in {g['solver']['elapsed_s']:.2f} s" if g.get("solver") else ""))
    for reason in g["reasons"]:
        print(f"  ! {reason}")
    for r_ in v["results"]:
        print(f"  {r_['result']:<4} {r_['rule_id']:<14} {r_['explanation']}")
    print(f"OVERALL: {v['overall']}  ({v['summary']['passed']} passed, {v['summary']['failed']} failed, "
          f"{v['summary']['not_applicable']} n/a)  -- geometric checks only, not a compliance statement")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(standalone_page(res["spec"]["meta"]["title"], res["html"]))
        print(f"wrote {a.out}")
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump({k: res[k] for k in ("spec", "generation", "validation")}, f, indent=2)
        print(f"wrote {a.json_out}")
    return 0 if v["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
