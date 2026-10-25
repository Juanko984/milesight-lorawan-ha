"""Smart-washroom maths: group the washroom devices by area into 'rooms' and roll up cleanliness (odour), supplies
(soap / paper / towels), traffic (visits since clean), air (CO2), noise and events (vaping, leak, smoke).
Pure Python (unit-tested). The hub tracker in washroom.py classifies devices and feeds this a flat list."""
from __future__ import annotations

from typing import Any

_ODOUR_RANK = {"Fresh": 0, "Noticeable": 1, "Strong": 2}
LOW_SUPPLY = 20          # % at or below which a consumable is "low"
OUT_SUPPLY = 5           # % at or below which it is "out"


def _worst_odour(vals: list[str]) -> str | None:
    vals = [v for v in vals if v in _ODOUR_RANK]
    return max(vals, key=lambda v: _ODOUR_RANK[v]) if vals else None


def compute_washroom(devices: list[dict[str, Any]]) -> dict[str, Any]:
    """devices: one dict per washroom device, already classified by the tracker:
      {area, name, core(bool), odour, nh3, h2s, co2, sound_db, occupied, people, remaining, supply_name,
       visits_since_clean, clean_due, clean_visits, vape, leak, smoke}
    Only areas that have at least one `core` washroom device (odour / vape / supply / occupancy / toilet) become
    rooms; other sensors in that area (CO2, noise, leak) are folded in."""
    areas: dict[str, list[dict]] = {}
    for d in devices:
        a = d.get("area") or "Washroom"
        areas.setdefault(a, []).append(d)

    rooms = []
    for area, ds in areas.items():
        if not any(d.get("core") for d in ds):
            continue
        odour = _worst_odour([d.get("odour") for d in ds])
        nh3 = max([d["nh3"] for d in ds if isinstance(d.get("nh3"), (int, float))], default=None)
        h2s = max([d["h2s"] for d in ds if isinstance(d.get("h2s"), (int, float))], default=None)
        co2 = max([d["co2"] for d in ds if isinstance(d.get("co2"), (int, float))], default=None)
        sound = max([d["sound_db"] for d in ds if isinstance(d.get("sound_db"), (int, float))], default=None)
        occupied = any(d.get("occupied") for d in ds)
        people = sum([d["people"] for d in ds if isinstance(d.get("people"), (int, float)) and not isinstance(d.get("people"), bool)]) or None
        supplies = [{"name": d.get("supply_name") or d.get("name") or "Supply", "remaining": round(float(d["remaining"]))}
                    for d in ds if isinstance(d.get("remaining"), (int, float))]
        supplies.sort(key=lambda s: s["remaining"])
        supply_min = supplies[0]["remaining"] if supplies else None
        clean = next((d for d in ds if d.get("clean_visits")), None)
        visits = clean.get("visits_since_clean") if clean else None
        clean_visits = clean.get("clean_visits") if clean else None
        clean_due = bool(clean and clean.get("clean_due"))
        vape = any(d.get("vape") for d in ds)
        leak = any(d.get("leak") for d in ds)
        smoke = any(d.get("smoke") for d in ds)

        odour_bad = odour == "Strong"
        odour_warn = odour == "Noticeable"
        co2_high = isinstance(co2, (int, float)) and co2 >= 1200
        issues = []
        if vape:
            issues.append({"level": "bad", "text": "Vaping detected"})
        if smoke:
            issues.append({"level": "bad", "text": "Smoke detected"})
        if leak:
            issues.append({"level": "bad", "text": "Leak detected"})
        if supply_min is not None and supply_min <= OUT_SUPPLY:
            issues.append({"level": "bad", "text": f"{supplies[0]['name']} empty"})
        if odour_bad:
            issues.append({"level": "warn", "text": "Strong odour · ventilate"})
        if co2_high:
            issues.append({"level": "warn", "text": f"CO₂ {round(co2)} ppm"})

        attention = bool(vape or smoke or leak or clean_due or odour_bad
                         or (supply_min is not None and supply_min <= LOW_SUPPLY))
        rooms.append({
            "area": area, "odour": odour, "odour_bad": odour_bad, "odour_warn": odour_warn,
            "nh3": nh3, "h2s": h2s, "co2": round(co2) if isinstance(co2, (int, float)) else None,
            "co2_high": co2_high, "sound_db": round(sound) if isinstance(sound, (int, float)) else None,
            "occupied": occupied, "people": people, "supplies": supplies, "supply_min": supply_min,
            "visits_since_clean": visits, "clean_visits": clean_visits, "clean_due": clean_due,
            "vape": vape, "leak": leak, "smoke": smoke, "issues": issues, "attention": attention,
        })

    # worst rooms first: anything with an alert, then clean-due, then low supply, then name
    def _rank(r):
        return (0 if (r["vape"] or r["leak"] or r["smoke"]) else 1, 0 if r["clean_due"] else 1,
                r["supply_min"] if r["supply_min"] is not None else 999, str(r["area"]).lower())
    rooms.sort(key=_rank)

    low = [r for r in rooms if r["supply_min"] is not None and r["supply_min"] <= LOW_SUPPLY]
    return {
        "rooms": rooms,
        "count": len(rooms),
        "need_cleaning": sum(1 for r in rooms if r["clean_due"]),
        "low_supplies": len(low),
        "odour_issues": sum(1 for r in rooms if r["odour_bad"] or r["co2_high"]),
        "alerts": sum(1 for r in rooms if r["vape"] or r["leak"] or r["smoke"]),
        "occupied_now": sum(1 for r in rooms if r["occupied"]),
    }
