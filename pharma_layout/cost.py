"""Indicative Total Investment Cost (TIC) - ILLUSTRATIVE SYNTHETIC ASSUMPTIONS, not market data, not quotations.

Every unit rate and equipment allowance below was INVENTED for this demonstration (currency: USD). None comes from a supplier,
a cost database or a standard. The point of this module is the transparent structure: quantity x rate = line, with a low/high
band and the formulas shown. Replace the tables with sourced data before drawing any conclusion from the numbers.
"""
from __future__ import annotations

CURRENCY = "USD (illustrative)"
LOW_FACTOR, HIGH_FACTOR = 0.80, 1.35        # applied to every rate / allowance: a stated band, not a statistical interval

# Synthetic room class per demo room id. NOT a cleanroom or regulatory classification; unknown ids fall back to "general".
ROOM_CLASS = {"MAL_IN": "airlock", "PAL": "airlock", "STG_IN": "storage", "STG_OUT": "storage", "WASTE": "storage",
              "DISP": "process", "GRAN": "process", "MILL": "process", "BLEND": "process", "COMP": "process", "COAT": "process",
              "IPC": "support", "WASH": "support", "CLEAN_EQ": "support"}
CLASS_NOTE = {"airlock": "airlock / transfer (assumed controlled)", "process": "process room (assumed controlled)",
              "storage": "storage / staging", "support": "support / lab", "general": "general"}
FITOUT_RATE = {"airlock": 2600, "process": 2200, "support": 1700, "storage": 1300, "general": 1400}   # USD per m2 construction + fit-out
HVAC_RATE = {"airlock": 1100, "process": 900, "support": 500, "storage": 350, "general": 300}        # USD per m2 HVAC / controlled-environment allowance
EQUIPMENT_ALLOWANCE = {"DISP": 180_000, "GRAN": 650_000, "MILL": 220_000, "BLEND": 260_000, "COMP": 900_000,
                       "COAT": 700_000, "IPC": 150_000, "WASH": 120_000}                               # USD lump sum per room, placeholder
UTILITIES_PCT, ENGINEERING_PCT, INSTALL_PCT_EQUIP, COMMISSIONING_PCT, CONTINGENCY_PCT = 0.12, 0.10, 0.20, 0.03, 0.20

EXCLUSIONS = ["Land, site works, external utilities and building shell outside the room envelope", "Taxes, duties, financing, escalation, currency effects",
              "Regulatory fees and any qualification / validation protocol work (no regulatory scope is modelled)",
              "Automation / IT, furniture, spares, operating costs", "Sizing of utilities and HVAC (flat allowances only)"]
ASSUMPTIONS = ["All rates, allowances and percentages are invented demonstration values (synthetic), not sourced industry data",
               "Quantities come from the placed room areas of the selected layout; equipment is a lump allowance per known demo room id",
               f"Low / high = base rates x {LOW_FACTOR:g} / x {HIGH_FACTOR:g} (a stated band, not a statistical interval)",
               "Room classes are a synthetic grouping for pricing, not a cleanroom grade or a regulatory classification"]


def estimate(spec: dict, placed: list[dict]) -> dict:
    by_id = {p["id"]: p for p in placed}
    area = {i: p["w"] * p["h"] for i, p in by_id.items()}
    cls = {r["id"]: ROOM_CLASS.get(r["id"], "general") for r in spec["rooms"] if r["id"] in by_id}
    lines = []

    def add(key, name, qty, unit, rate, formula, base):
        lines.append({"key": key, "component": name, "quantity": qty, "unit": unit, "rate": rate, "formula": formula,
                      "low": base * LOW_FACTOR, "base": base, "high": base * HIGH_FACTOR})

    fit = sum(area[i] * FITOUT_RATE[c] for i, c in cls.items()); hv = sum(area[i] * HVAC_RATE[c] for i, c in cls.items())
    eq = sum(EQUIPMENT_ALLOWANCE.get(i, 0) for i in cls)
    total_area = sum(area.values())
    add("construction", "Building and room construction / fit-out", round(total_area, 1), "m2 placed", "by class, 1,300-2,600 USD/m2",
        "sum over rooms of area x class rate", fit)
    add("equipment", "Process equipment (placeholder allowances)", sum(1 for i in cls if i in EQUIPMENT_ALLOWANCE), "rooms with equipment",
        "lump sum per room, 120k-900k USD", "sum of per-room allowances", eq)
    add("hvac", "HVAC and controlled-environment systems", round(total_area, 1), "m2 placed", "by class, 300-1,100 USD/m2",
        "sum over rooms of area x class rate", hv)
    util = UTILITIES_PCT * (fit + eq + hv)
    add("utilities", "Utilities (electrical, compressed air, water, drainage)", "-", "", f"{UTILITIES_PCT:.0%}", "12 % x (construction + equipment + HVAC)", util)
    eng = ENGINEERING_PCT * (fit + eq + hv + util)
    add("engineering", "Engineering, design and project management", "-", "", f"{ENGINEERING_PCT:.0%}", "10 % x (construction + equipment + HVAC + utilities)", eng)
    inst = INSTALL_PCT_EQUIP * eq
    add("installation", "Equipment installation", "-", "", f"{INSTALL_PCT_EQUIP:.0%}", "20 % x equipment", inst)
    direct = fit + eq + hv + util + eng + inst
    comm = COMMISSIONING_PCT * direct
    add("commissioning", "Commissioning allowance", "-", "", f"{COMMISSIONING_PCT:.0%}", "3 % x sum of the lines above", comm)
    cont = CONTINGENCY_PCT * (direct + comm)
    add("contingency", "Contingency", "-", "", f"{CONTINGENCY_PCT:.0%}", "20 % x sum of all lines above", cont)
    tot = {k: sum(l[k] for l in lines) for k in ("low", "base", "high")}
    drivers = sorted(lines, key=lambda l: -l["base"])[:3]
    return {"currency": CURRENCY, "lines": lines, "total": tot, "per_m2_base": tot["base"] / total_area if total_area else None,
            "area_m2": total_area, "drivers": [(l["component"], l["base"] / tot["base"]) for l in drivers],
            "exclusions": EXCLUSIONS, "assumptions": ASSUMPTIONS, "classes": cls,
            "label": "ILLUSTRATIVE ONLY: invented synthetic rates, not verified market quotations, not sourced industry data."}
