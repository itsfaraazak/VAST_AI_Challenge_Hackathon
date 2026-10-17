"""Catalog of common/sabotage breadboard mistakes with deterministic detectors.

diagnose(twin, findings, step) -> list of {id,title,severity,parts,pins,explain,fix}.
Best effort; robust to None/partial twins. Never raises.
"""
from __future__ import annotations

import json
import re
from typing import Any

_SIGNAL = re.compile(r"\.(d13|gpio2|gpio\d+|d\d+)$", re.I)


def _ctx(twin, findings) -> dict:
    twin = twin if isinstance(twin, dict) else {}
    comps = [c for c in (twin.get("components") or []) if isinstance(c, dict)]
    nets = [[str(e) for e in n] for n in (twin.get("nets") or []) if isinstance(n, (list, tuple))]
    fids = {str(f.get("id")) for f in (findings or []) if isinstance(f, dict)}
    ftxt = " ".join(str(f.get("message", "")) for f in (findings or []) if isinstance(f, dict)).lower()
    try:
        extra = json.dumps({"o": twin.get("observation"), "w": twin.get("wiring_check")}, default=str).lower()
    except Exception:  # noqa: BLE001
        extra = ""
    by_type: dict[str, list[str]] = {}
    for c in comps:
        by_type.setdefault(str(c.get("type", "")).lower(), []).append(str(c.get("id")))
    return {"comps": comps, "nets": nets, "fids": fids, "text": ftxt + " " + extra, "types": by_type}


def _net_of(c, ep: str) -> list[str]:
    ep = ep.lower()
    for n in c["nets"]:
        if ep in [e.lower() for e in n]:
            return n
    return []


def _any(net, pred) -> bool:
    return any(pred(e.lower()) for e in net)


def _is_gnd(e: str) -> bool:
    return e.startswith("gnd.") or e.endswith(".gnd") or e.endswith(".neg")


def _is_5v(e: str) -> bool:
    return e.endswith((".5v", ".vin", ".vcc", ".pos", ".vbus"))


def _is_3v3(e: str) -> bool:
    return e.endswith((".3v3", ".3.3v", ".3v"))


def _is_sig(e: str) -> bool:
    return bool(_SIGNAL.search(e))


def _has(c, t): return bool(c["types"].get(t))


def _led_eps(c):
    return [(i, f"{i}.a", f"{i}.k") for i in c["types"].get("led", [])]


def d_led_reversed(c):
    if "led_reversed" in c["fids"]:
        return True
    for _, a, k in _led_eps(c):
        if _any(_net_of(c, a), _is_gnd) or _any(_net_of(c, k), lambda e: _is_sig(e) or _is_5v(e) or _is_3v3(e)):
            return True
    return False


def d_no_resistor(c):
    if "led_no_series_resistor" in c["fids"]:
        return True
    return _has(c, "led") and not _has(c, "resistor") and bool(c["nets"])


def d_resistor_5v(c):
    for r in c["types"].get("resistor", []):
        for p in ("a", "b", "1", "2"):
            if _any(_net_of(c, f"{r}.{p}"), _is_5v):
                return True
    return False


def d_3v3_not_signal(c):
    for i, a, _ in _led_eps(c):
        n = _net_of(c, a)
        if _any(n, _is_3v3) and not _any(n, _is_sig):
            return True
    for r in c["types"].get("resistor", []):
        for p in ("a", "b"):
            n = _net_of(c, f"{r}.{p}")
            if _any(n, _is_3v3) and not _any(n, _is_sig) and "nano" in c["text"] + " ".join(e for x in c["nets"] for e in x).lower():
                return True
    return False


def d_gnd_missing(c):
    if not (_has(c, "led") and _has(c, "resistor")):
        return False
    for _, _, k in _led_eps(c):
        if not _any(_net_of(c, k), _is_gnd):
            return True
    return False


def d_not_same_strip(c):
    """LED and resistor both exist but no net links them (wrong row/strip)."""
    if not (_has(c, "led") and _has(c, "resistor")) or not c["nets"]:
        return False
    rs = set(c["types"]["resistor"])
    for i, a, k in _led_eps(c):
        for n in (_net_of(c, a), _net_of(c, k)):
            if any(e.split(".")[0] in rs for e in n):
                return False
    return True


def d_short_same_row(c):
    if "supply_short" in c["fids"] or "short" in c["fids"]:
        return True
    t = c["text"]
    if re.search(r"same (row|strip|column)", t) and "short" in t:
        return True
    for i, a, k in _led_eps(c):
        if a.lower() in [e.lower() for e in _net_of(c, a)] and k.lower() in [e.lower() for e in _net_of(c, a)]:
            return True
    for r in c["types"].get("resistor", []):
        n = _net_of(c, f"{r}.a")
        if f"{r}.b".lower() in [e.lower() for e in n]:
            return True
    return False


def d_overcurrent(c):
    return "led_overcurrent" in c["fids"] or "resistor_too_small" in c["fids"]


def d_usb(c):
    t = c["text"]
    return bool(re.search(r"(no|without|missing|unplugged|not connected)[^\"]{0,20}usb|usb[^\"]{0,20}(unplugged|not (connected|plugged)|missing)|\"usb\": ?(false|\"no)", t))


def d_straddle(c):
    t = c["text"]
    return bool(re.search(r"straddl|center (channel|gap)|centre (channel|gap)|(all|both) (rows|pins)[^\"]{0,30}same side", t)) and bool(
        re.search(r"not|wrong|bad|no |false|same side|missing|fail", t))


def d_jumper_wrong_row(c):
    t = c["text"]
    return bool(re.search(r"jumper[^\"]{0,40}(same row|wrong row|adjacent pin|neighbou?r)|(same row|wrong row)[^\"]{0,40}jumper", t))


M = [
    dict(id="led_reversed", title="LED is backwards", severity="critical", detect=d_led_reversed,
         parts=["led"], pins=["D13", "GND"],
         explain="current only flows anode to cathode, so a reversed LED blocks it and stays dark.",
         fix="Swap the LED so the long leg (anode) faces the resistor and the short leg faces GND."),
    dict(id="resistor_missing", title="No series resistor", severity="critical", detect=d_no_resistor,
         parts=["led", "resistor"], pins=["D13"],
         explain="with nothing limiting current the LED draws well past 20 mA and can burn out.",
         fix="Add a 220 ohm resistor between D13 and the LED long leg."),
    dict(id="resistor_to_5v", title="Resistor goes to 5V instead of the pin", severity="critical", detect=d_resistor_5v,
         parts=["resistor"], pins=["5V", "D13"],
         explain="tied to 5V the LED is always on and the sketch can never blink it.",
         fix="Move the resistor's free end from 5V to the D13 row."),
    dict(id="used_3v3_not_signal", title="Using 3V3 instead of the signal pin", severity="critical", detect=d_3v3_not_signal,
         parts=["led", "resistor"], pins=["3V3", "D13"],
         explain="3V3 is a fixed supply, not a programmable output, so the sketch cannot toggle it.",
         fix="Move that wire from 3V3 to D13 (GPIO2 on an ESP32)."),
    dict(id="gnd_missing", title="Cathode not connected to GND", severity="critical", detect=d_gnd_missing,
         parts=["led", "wire"], pins=["GND"],
         explain="without a return path to GND no current can flow through the LED.",
         fix="Jumper the LED short-leg row to any GND pin."),
    dict(id="not_same_strip", title="Resistor and LED are not in the same column strip", severity="warning", detect=d_not_same_strip,
         parts=["resistor", "led"], pins=[],
         explain="each 5-hole strip is one node, so parts in different strips are not connected.",
         fix="Move the resistor's second leg into the same 5-hole strip as the LED long leg."),
    dict(id="legs_shorted", title="Component legs in the same row", severity="critical", detect=d_short_same_row,
         parts=["led", "resistor"], pins=[],
         explain="both legs in one strip are shorted together, so the part does nothing (or shorts the supply).",
         fix="Move one leg to a different row, one strip apart."),
    dict(id="led_overcurrent", title="LED current too high", severity="critical", detect=d_overcurrent,
         parts=["led", "resistor"], pins=["D13"],
         explain="more than 20 mA damages the LED and stresses the pin.",
         fix="Use 220 ohm or larger in series with the LED."),
    dict(id="usb_missing", title="USB is not connected", severity="warning", detect=d_usb,
         parts=["nano"], pins=[],
         explain="with no USB power the board is off, so nothing runs even if the wiring is perfect.",
         fix="Plug the USB cable into the board and your computer."),
    dict(id="board_straddle", title="Board not straddling the center channel", severity="warning", detect=d_straddle,
         parts=["nano", "breadboard"], pins=[],
         explain="pins on both sides land in the same strips and short together.",
         fix="Press the board across the center channel so each side has its own rows."),
    dict(id="jumper_wrong_row", title="Jumper shares a row with another pin", severity="warning", detect=d_jumper_wrong_row,
         parts=["wire"], pins=[],
         explain="a jumper in a neighbouring pin's row connects to that pin, not to D13.",
         fix="Move the jumper into the row of the pin you intend (D13)."),
]


def diagnose(twin, findings=None, step=None) -> list[dict]:
    try:
        c = _ctx(twin, findings)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for m in M:
        try:
            if m["detect"](c):
                out.append({k: v for k, v in m.items() if k != "detect"})
        except Exception:  # noqa: BLE001
            continue
    return out


def public(ms: list[dict]) -> list[dict]:
    return [{k: m[k] for k in ("id", "title", "severity", "parts", "pins", "fix")} for m in ms]
