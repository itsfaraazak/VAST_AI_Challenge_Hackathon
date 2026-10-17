"""Normalize twin for deterministic verification."""
from __future__ import annotations

from typing import Any

LED_VF = {"red": 1.8, "green": 2.1, "blue": 3.0, "white": 3.2, "yellow": 2.0, "default": 2.0}
LED_RS = 10.0  # series ohms in piecewise-linear model


def normalize(twin: dict, supply_voltage: float = 5.0) -> dict:
    comps = []
    for c in twin.get("components") or []:
        ctype = str(c.get("type", "")).lower()
        cid = str(c.get("id"))
        val = c.get("value")
        n: dict[str, Any] = {"id": cid, "type": ctype, "value": val}
        if ctype == "resistor":
            n["ohms"] = _ohms(val, default=220.0)
            n["power_w"] = _power_rating(val, default=0.25)
        elif ctype == "led":
            color = str(val or "red").lower()
            n["color"] = color
            n["vf"] = LED_VF.get(color, LED_VF["default"])
            n["rs"] = LED_RS
            n["anode"] = "a"
            n["cathode"] = "k"
        elif ctype in ("battery", "supply"):
            n["type"] = "supply"
            n["volts"] = float(val) if _is_number(val) else float(supply_voltage)
        elif ctype == "switch":
            n["closed"] = str(val).lower() not in ("open", "0", "false", "off")
        comps.append(n)
    nets = []
    for net in twin.get("nets") or []:
        nets.append([str(e) for e in net])
    sv = twin.get("supply_voltage", supply_voltage)
    return {"components": comps, "nets": nets, "supply_voltage": float(sv)}


def _is_number(v: Any) -> bool:
    try:
        float(str(v).lower().replace("ohm", "").replace("Ω", "").replace("v", "").strip())
        return True
    except Exception:  # noqa: BLE001
        return False


def _ohms(val: Any, default: float) -> float:
    if val is None:
        return default
    s = str(val).strip().lower().replace("ohm", "").replace("Ω", "").replace(" ", "")
    mult = 1.0
    if s.endswith("k"):
        mult = 1e3
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1e6
        s = s[:-1]
    try:
        return float(s) * mult
    except Exception:  # noqa: BLE001
        return default


def _power_rating(val: Any, default: float) -> float:
    # optional "220/0.25W"
    if isinstance(val, str) and "w" in val.lower():
        try:
            return float(val.lower().split("/")[-1].replace("w", ""))
        except Exception:  # noqa: BLE001
            return default
    return default
