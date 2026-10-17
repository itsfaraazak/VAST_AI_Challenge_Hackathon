"""Strict twin JSON parser. Never trust unparsed LLM output."""
from __future__ import annotations

import json
import re
from typing import Any

ALLOWED_TYPES = {
    "resistor", "led", "battery", "supply", "switch", "wire",
    "capacitor", "diode", "arduino", "raspberry-pi", "breadboard", "unknown",
}


class TwinParseError(ValueError):
    pass


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise TwinParseError("no JSON object found")
        return json.loads(m.group(0))


def parse_twin(raw: str | dict) -> dict:
    data = raw if isinstance(raw, dict) else _extract_json(raw)
    if not isinstance(data, dict):
        raise TwinParseError("root must be object")

    scene = str(data.get("scene") or "bench").lower()
    if scene not in ("bench", "other"):
        scene = "bench"

    comps = data.get("components")
    nets = data.get("nets")
    if comps is None:
        comps = []
    if nets is None:
        nets = []
    if not isinstance(comps, list) or not isinstance(nets, list):
        raise TwinParseError("components and nets must be lists")

    # Empty twin is valid for scene=other
    out_comps = []
    ids: set[str] = set()
    for i, c in enumerate(comps):
        if not isinstance(c, dict):
            raise TwinParseError(f"component[{i}] not object")
        cid = str(c.get("id", "")).strip()
        ctype = str(c.get("type", "")).strip().lower().replace(" ", "-")
        if not cid or not ctype:
            raise TwinParseError(f"component[{i}] missing id/type")
        if cid in ids:
            raise TwinParseError(f"duplicate id {cid}")
        ids.add(cid)
        if ctype not in ALLOWED_TYPES:
            ctype = "unknown"
        out_comps.append({"id": cid, "type": ctype, "value": c.get("value")})

    out_nets = []
    for i, net in enumerate(nets):
        if not isinstance(net, list) or len(net) < 2:
            raise TwinParseError(f"nets[{i}] must be list of >=2 endpoints")
        ends = []
        for e in net:
            s = str(e).strip()
            if "." not in s:
                raise TwinParseError(f"endpoint {s!r} must be id.pin")
            ends.append(s)
        out_nets.append(ends)

    placements = data.get("placements") or []
    if not isinstance(placements, list):
        placements = []

    wiring_check = data.get("wiring_check")
    if wiring_check is not None and not isinstance(wiring_check, dict):
        wiring_check = None

    twin: dict[str, Any] = {
        "scene": scene,
        "observation": str(data.get("observation") or "").strip(),
        "components": out_comps,
        "nets": out_nets,
        "placements": placements,
    }
    if wiring_check is not None:
        twin["wiring_check"] = wiring_check
    supply = data.get("supply_voltage", data.get("supply_v"))
    if supply is not None:
        twin["supply_voltage"] = float(supply)
    return twin
