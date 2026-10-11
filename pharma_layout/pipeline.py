"""spec -> generate -> validate -> report. Single entry point used by CLI, server and tests."""
from __future__ import annotations

from .generator import generate_layout
from .report import render_report
from .spec import GENERATOR_METHODS, SpecError, validate_spec
from .validator import validate_layout


def run_pipeline(raw_spec, method: str | None = None) -> dict:
    """Raises ``SpecError`` for invalid input. Otherwise always returns a result,
    including for infeasible specs (with an explanation and no placements).
    ``method`` overrides ``spec["generator"]["method"]`` (the override is recorded in the returned spec)."""
    spec = validate_spec(raw_spec)
    if method is not None:
        if method not in GENERATOR_METHODS:
            raise SpecError([f"method: must be one of {list(GENERATOR_METHODS)} (got {method!r})"])
        spec["generator"]["method"] = method
    generation = generate_layout(spec)
    validation = validate_layout(spec, generation["rooms"])

    notes: list[str] = []
    sr = generation["self_report"]
    if generation["status"] == "placed":
        gen_unsat = set(sr["unsatisfied_adjacency"])
        val_unsat = {r["rule_id"].split(":", 1)[1] for r in validation["results"]
                     if r["rule_id"].startswith("V-08:") and r["result"] == "FAIL"}
        if gen_unsat != val_unsat:
            notes.append("Generator self-report and validator disagree on adjacency "
                         f"(generator: {sorted(gen_unsat)}, validator: {sorted(val_unsat)}). Trust the validator and report this as a bug.")
    if generation["status"] == "placed" and validation["overall"] != "PASS" and generation["method"]["name"] == "cp-sat":
        failed = sorted({r["rule_id"].split(":")[0] for r in validation["results"] if r["result"] == "FAIL"})
        notes.append("CP-SAT returned a candidate that FAILED independent validation "
                     f"({', '.join(failed)}), so it is reported as a failure, not a success. This points to a mismatch between "
                     "the grid model and the validator (a bug or a discretisation effect); the validator is authoritative.")
    html = render_report(spec, generation, validation, notes)
    return {"spec": spec, "generation": generation, "validation": validation, "html": html, "notes": notes}
