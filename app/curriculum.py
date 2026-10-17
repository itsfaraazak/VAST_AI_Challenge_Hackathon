"""Blink-on-Nano curriculum — technically correct wiring + teaching beats."""
from __future__ import annotations

from copy import deepcopy

# Canonical external Blink wiring (Arduino Nano, ATmega328):
#   D13 --[220Ω]-- LED anode (long) ; LED cathode (short) -- GND
# Built-in LED on D13 shares that pin; we teach an *external* LED on the breadboard.

BLINK_NANO_PROJECT = {
    "id": "blink",
    "title": "Blink — external LED on Arduino Nano",
    "pitch": "Wire one LED so pin D13 can blink it safely through a 220Ω resistor.",
    "mcu": "Arduino Nano (ATmega328)",
    "sketch": "File → Examples → 01.Basics → Blink (pin 13)",
    "steps": [
        {
            "id": "orient",
            "why": 'Pin D13 is wired to the ATmega328 PB5 output: HIGH = 5 V, LOW = 0 V, and each pin can source about 20 mA, so every pin needs its own row to be usable.',
            "check": 'Quick check: which Nano pin will drive the LED, and what voltage is it at when HIGH?',
            "hole_hint": 'Straddle the center channel: left-edge pins in rows on one side, right-edge pins on the other. D13 and its row share one column strip (A-E or F-J).',
            "title": "Orient the Nano and breadboard",
            "concept": "The Nano’s USB faces “up”. Digital pins are on both long edges; D13 sits next to the 3V3 pin on the right edge when USB is up.",
            "action": "Seat the Nano across the breadboard center channel so each pin has its own row. Leave the power rails free on both sides.",
            "teach": "We will use D13 (signal) and a GND pin. Never short 5V straight into an LED.",
            "expect": {"has_board": True},
            "pins": ["D13", "GND"],
            "wires": [],
            "parts": ["nano", "breadboard"],
        },
        {
            "id": "led",
            "why": 'An LED only conducts anode to cathode, once the forward voltage is passed (about 1.8 V for red); the long leg is the anode.',
            "check": 'Quick check: which LED leg is the anode, long or short?',
            "hole_hint": 'LED legs go in two different rows (never the same row, or you short it). Long leg row = the resistor row, short leg row = the ground row.',
            "title": "Seat the LED (polarity matters)",
            "concept": "LEDs are diodes. Current flows anode → cathode. The long leg is the anode; the short leg / flat side is the cathode.",
            "action": "Place the LED across two empty rows below the Nano. Long leg toward the side that will meet the resistor; short leg toward the ground rail.",
            "teach": "If you reverse it, the Blink sketch will look “dead” even when the wiring is otherwise fine.",
            "expect": {"types": ["led"]},
            "pins": ["D13", "GND"],
            "wires": [],
            "parts": ["led"],
        },
        {
            "id": "resistor",
            "why": "Ohm's law: R = (5 V - 1.8 V) / 0.015 A = 213 ohm, so 220 ohm gives about 14.5 mA, safely under the 20 mA limit.",
            "check": 'Quick check: what current flows with 220 ohm at 5 V and a 1.8 V LED?',
            "hole_hint": 'Resistor leg 1 in the same column strip as the D13 jumper/pin row; leg 2 in the same strip as the LED long leg (anode).',
            "title": "Add a 220Ω series resistor",
            "concept": "Without a series resistor, LED current can spike past ~20 mA and burn the LED (or stress the pin). V ≈ 5 V, Vf(red) ≈ 1.8 V → R ≈ (5−1.8)/0.015 ≈ 220Ω.",
            "action": "Put a 220Ω (red-red-brown) resistor from the Nano’s D13 row to the LED anode row.",
            "teach": "Series means: pin → resistor → LED → ground. The resistor and LED share one node at the anode.",
            "expect": {"types": ["led", "resistor"]},
            "pins": ["D13"],
            "wires": [
                {"from": "D13", "to": "R220.a", "color": "#c87941"},
                {"from": "R220.b", "to": "LED.a", "color": "#d6ff4b"},
            ],
            "parts": ["resistor"],
        },
        {
            "id": "gnd",
            "why": 'Current needs a closed loop; the cathode must reach GND (0 V) or no voltage drops across the LED and nothing flows.',
            "check": 'Quick check: where does the current return to?',
            "hole_hint": 'Jumper from the same column strip as the LED short leg (cathode) to any Nano GND pin row, or the GND rail.',
            "title": "Close the circuit to GND",
            "concept": "A circuit needs a return path. Cathode must reach Nano GND (any GND pin is fine).",
            "action": "Jumper the LED cathode row to a GND pin on the Nano (or to the blue ground rail already tied to GND).",
            "teach": "Path is now: D13 → 220Ω → LED → GND. That is the whole Blink circuit.",
            "expect": {"types": ["led", "resistor"], "gnd": True},
            "pins": ["GND"],
            "wires": [
                {"from": "D13", "to": "R220.a", "color": "#c87941"},
                {"from": "R220.b", "to": "LED.a", "color": "#d6ff4b"},
                {"from": "LED.k", "to": "GND", "color": "#5b8def"},
            ],
            "parts": ["wire"],
        },
        {
            "id": "flash",
            "why": 'Blink toggles D13 HIGH (5 V, LED on, about 14.5 mA) then LOW (0 V, off) every 1000 ms, so the LED flashes once a second.',
            "check": 'Quick check: what voltage is on D13 when the LED is off?',
            "hole_hint": 'Nothing new to wire: USB into the Nano, board "Arduino Nano", pick the port, Upload.',
            "title": "Power up and run Blink",
            "concept": "The stock Blink sketch toggles pin 13 HIGH/LOW once per second. External LED on D13 follows the built-in LED.",
            "action": "Plug USB, open Arduino IDE → Examples → 01.Basics → Blink → Upload. Watch the external LED breathe.",
            "teach": "If it stays dark: check cathode→GND, resistor on D13 (not 5V), and that Upload selected “Arduino Nano”.",
            "expect": {"complete": True},
            "pins": ["D13", "GND", "5V"],
            "wires": [
                {"from": "D13", "to": "R220.a", "color": "#c87941"},
                {"from": "R220.b", "to": "LED.a", "color": "#d6ff4b"},
                {"from": "LED.k", "to": "GND", "color": "#5b8def"},
            ],
            "parts": [],
        },
    ],
}

BLINK_PROJECT = BLINK_NANO_PROJECT  # backward-compatible alias

BOARDS = {
    "nano": {"name": "Arduino Nano", "logic_v": 5.0, "signal_pin": "D13", "gnd_pin": "GND"},
    "esp32": {"name": "ESP32 DevKit", "logic_v": 3.3, "signal_pin": "GPIO2", "gnd_pin": "GND"},
}


def _esp32_variant() -> dict:
    p = deepcopy(BLINK_NANO_PROJECT)
    p["board"] = "esp32"
    p["title"] = "Blink — external LED on ESP32 DevKit"
    p["pitch"] = "Wire one LED so GPIO2 (3.3 V logic) can blink it safely through a 220 ohm resistor."
    p["mcu"] = "ESP32 DevKit (ESP32-WROOM)"
    p["sketch"] = "Arduino IDE, board 'ESP32 Dev Module': Blink with LED_BUILTIN / GPIO2"
    notes = {
        "orient": ("The ESP32 DevKit is wider than a Nano. Find GPIO2 and a GND pin on the silkscreen; GPIO2 also drives the on-board blue LED on most DevKits.",
                   "Seat the DevKit so its two pin rows straddle the center channel with a free row beside GPIO2 and beside GND.",
                   "GPIO2 is 3.3 V logic: HIGH = 3.3 V, not 5 V. Never wire 5V/VIN to the LED.",
                   "GPIO2 outputs 3.3 V when HIGH and tolerates only about 12 mA per pin comfortably.",
                   "Quick check: what voltage is GPIO2 when HIGH?",
                   "Same rule as the Nano: GPIO2 and its jumper share one column strip; leave the neighbouring row free."),
        "led": (None, None, None, "Same LED physics: conducts anode to cathode above about 1.8 V forward voltage (red).", None, None),
        "resistor": ("At 3.3 V the LED is dimmer but safe.", "Put a 220 ohm (red-red-brown) resistor from the GPIO2 row to the LED anode row.",
                     "Series means GPIO2 -> resistor -> LED -> GND.",
                     "Ohm's law at 3.3 V: (3.3 - 1.8) / 220 = 6.8 mA. Dimmer than on a Nano but plenty visible and safe; 220 ohm is still fine.",
                     "Quick check: what current at 3.3 V with 220 ohm?",
                     "Resistor leg 1 in the same column strip as the GPIO2 jumper; leg 2 in the same strip as the LED long leg."),
        "gnd": (None, "Jumper the LED cathode row to a GND pin on the ESP32 (or the GND rail tied to it).",
                "Path: GPIO2 -> 220 ohm -> LED -> GND.", None, None,
                "Jumper from the LED short-leg strip to an ESP32 GND pin row."),
        "flash": ("The same Blink sketch toggles GPIO2 HIGH/LOW once per second.",
                  "Plug USB, Arduino IDE, board 'ESP32 Dev Module', pick the port, upload Blink using LED_BUILTIN (GPIO2). Hold BOOT if upload stalls.",
                  "If it stays dark: cathode to GND, resistor on GPIO2 (not 3V3), correct board selected.",
                  "GPIO2 toggles between 3.3 V (about 6.8 mA, LED on) and 0 V (off) every 1000 ms.",
                  "Quick check: what voltage is on GPIO2 when the LED is off?",
                  "Nothing new to wire: USB into the DevKit, board 'ESP32 Dev Module'."),
    }
    for st in p["steps"]:
        n = notes.get(st["id"])
        if n:
            concept, action, teach, why, check, hole = n
            if concept: st["concept"] = concept
            if action: st["action"] = action
            if teach: st["teach"] = teach
            if why: st["why"] = why
            if check: st["check"] = check
            if hole: st["hole_hint"] = hole
        st["pins"] = ["GPIO2" if x == "D13" else ("3V3" if x == "5V" else x) for x in st.get("pins", [])]
        st["parts"] = ["esp32" if x == "nano" else x for x in st.get("parts", [])]
        for w in st.get("wires", []):
            if w["from"] == "D13": w["from"] = "GPIO2"
        st["concept"] = st["concept"].replace("D13", "GPIO2").replace("Nano", "ESP32")
        st["action"] = st["action"].replace("D13", "GPIO2").replace("Nano", "ESP32")
        st["teach"] = st["teach"].replace("D13", "GPIO2").replace("Nano", "ESP32").replace("5V straight", "3V3 straight")
    return p


PROJECTS = {
    "blink": BLINK_NANO_PROJECT,
}


def normalize_board(board: str | None) -> str:
    b = (board or "nano").lower()
    return "esp32" if "esp" in b else "nano"


def list_projects() -> list[dict]:
    return [
        {"id": p["id"], "title": p["title"], "pitch": p["pitch"]}
        for p in PROJECTS.values()
    ]


def get_project(project_id: str, board: str | None = None) -> dict | None:
    """Backward compatible: get_project('blink') -> nano. board in ('nano','esp32')."""
    p = PROJECTS.get(project_id)
    if not p:
        return None
    if project_id == "blink" and normalize_board(board) == "esp32":
        return _esp32_variant()
    q = deepcopy(p)
    q.setdefault("board", "nano")
    return q


def step_at(project: dict, index: int) -> dict | None:
    steps = project.get("steps") or []
    if index < 0 or index >= len(steps):
        return None
    return steps[index]


def infer_step_from_twin(project: dict, twin: dict | None) -> int:
    """Heuristic progress from Cosmos twin types (best-effort)."""
    if not twin:
        return 0
    types = {str(c.get("type", "")).lower() for c in (twin.get("components") or [])}
    if "led" in types and "resistor" in types:
        # assume GND likely once both present — user may still be on gnd step
        return 3
    if "led" in types:
        return 2
    if types:
        return 1
    return 0


# ---------------------------------------------------------------------------
# LLM-generated projects: parse, repair, validate
# ---------------------------------------------------------------------------
import json as _json
import re as _re

MAX_STEPS = 7
_NANO_PINS = {f"D{i}" for i in range(2, 14)} | {f"A{i}" for i in range(6)} | {"5V", "3V3", "GND", "VIN"}
_POWER = {"5V", "3V3", "VIN"}
_PART_RE = _re.compile(r"^[A-Za-z]{1,6}\d{0,2}\.[A-Za-z0-9]{1,2}$")
_COLORS = ["#c87941", "#d6ff4b", "#5b8def", "#ff6b6b", "#b48cff", "#4bd6c8"]


def slugify(text: str) -> str:
    s = _re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:32].strip("-")) or "project"


def repair_json(text: str) -> str:
    """Salvage fenced / truncated JSON (same idea as perception.cosmos._repair)."""
    t = (text or "").strip()
    t = _re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i = t.find("{")
    if i < 0:
        return t
    t = t[i:]
    try:
        _json.loads(t)
        return t
    except ValueError:
        pass
    for cut in range(len(t), 0, -1):
        if t[cut - 1] not in ",]}":
            continue
        cand = t[:cut].rstrip(",")
        stack, in_str, esc = [], False, False
        for ch in cand:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_str:
            continue
        try:
            _json.loads(cand + "".join(reversed(stack)))
            return cand + "".join(reversed(stack))
        except ValueError:
            continue
    return t


def norm_endpoint(ep, board: str) -> str | None:
    """Return canonical endpoint or None if invalid for this board."""
    e = str(ep or "").strip().replace(" ", "")
    if not e:
        return None
    u = e.upper()
    if "." in u:
        return u if _PART_RE.match(e) and not u.startswith(("D13.", "GPIO")) else None
    if u in ("GND", "3V3", "5V", "VIN"):
        if board == "esp32" and u in ("5V", "VIN"):
            return None
        return u
    if board == "nano":
        return u if u in _NANO_PINS else None
    m = _re.match(r"^(?:GPIO|IO|D)(\d{1,2})$", u)
    if m and int(m.group(1)) <= 39:
        return f"GPIO{int(m.group(1))}"
    return None


def _clean_wires(wires, board: str) -> list[dict]:
    out = []
    for i, w in enumerate(wires if isinstance(wires, list) else []):
        if not isinstance(w, dict):
            raise ValueError("wire not an object")
        a, b = norm_endpoint(w.get("from"), board), norm_endpoint(w.get("to"), board)
        if not a or not b:
            raise ValueError(f"bad wire endpoint {w.get('from')}->{w.get('to')} for {board}")
        if a == b:
            raise ValueError("wire loops to itself")
        pins = [x for x in (a, b) if "." not in x]
        if len(pins) == 2:  # pin-to-pin jumper: shorts if any side is a rail or both are rails
            if (a in _POWER | {"GND"}) and (b in _POWER | {"GND"}):
                raise ValueError(f"short {a}-{b}")
            if a in _POWER | {"GND"} or b in _POWER | {"GND"}:
                raise ValueError(f"pin shorted to rail {a}-{b}")
        col = w.get("color") if isinstance(w.get("color"), str) and w["color"].startswith("#") else _COLORS[i % len(_COLORS)]
        out.append({"from": a, "to": b, "color": col})
    return out


def validate_project(raw: dict, board: str, prompt: str = "") -> dict:
    """Coerce an LLM dict into the BLINK_PROJECT shape or raise ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    board = normalize_board(board)
    steps_in = raw.get("steps")
    if not isinstance(steps_in, list) or len(steps_in) < 2:
        raise ValueError("need >=2 steps")
    steps = []
    for i, s in enumerate(steps_in[:MAX_STEPS]):
        if not isinstance(s, dict):
            raise ValueError("step not an object")
        wires = _clean_wires(s.get("wires"), board)
        pins = []
        for p in s.get("pins") or []:
            q = norm_endpoint(p, board)
            if q and "." not in q:
                pins.append(q)
        t = lambda k, d="": str(s.get(k) or d).strip()[:400]  # noqa: E731
        exp = s.get("expect") if isinstance(s.get("expect"), dict) else {}
        steps.append({
            "id": slugify(t("id", f"step{i + 1}")) or f"step{i + 1}",
            "title": t("title", f"Step {i + 1}"),
            "concept": t("concept"), "action": t("action", t("title")),
            "teach": t("teach"), "why": t("why"), "check": t("check"),
            "hole_hint": t("hole_hint"), "expect": exp, "pins": pins, "wires": wires,
            "parts": [str(x)[:24] for x in (s.get("parts") or []) if isinstance(x, (str, int))][:8],
        })
    if len({s["id"] for s in steps}) != len(steps):
        for i, s in enumerate(steps):
            s["id"] = f"{s['id']}-{i + 1}"
    steps[-1]["expect"] = steps[-1]["expect"] or {"complete": True}
    # safety: every LED must have a series resistor somewhere in the wiring
    allw = [w for s in steps for w in s["wires"]]
    ends = {e for w in allw for e in (w["from"], w["to"])}
    plist = raw.get("parts_list") if isinstance(raw.get("parts_list"), list) else []
    has_led = any(e.startswith("LED") for e in ends) or any(
        isinstance(p, dict) and "led" in str(p.get("type", "")).lower() for p in plist)
    if has_led and not any(e.startswith("R") and "." in e for e in ends):
        raise ValueError("LED without a series resistor")
    # LED anode must not wire straight to a pin/rail
    for w in allw:
        for x, y in ((w["from"], w["to"]), (w["to"], w["from"])):
            if x.startswith("LED") and x.endswith(".A") and "." not in y and y != "GND":
                raise ValueError("LED anode wired straight to a pin (no resistor)")
    title = str(raw.get("title") or prompt or "Custom project").strip()[:80]
    pl = []
    for p in plist[:12]:
        if isinstance(p, dict):
            try:
                qty = max(1, min(20, int(p.get("qty") or 1)))
            except (TypeError, ValueError):
                qty = 1
            pl.append({"type": str(p.get("type", ""))[:30], "value": str(p.get("value", ""))[:20], "qty": qty})
    sketch = "\n".join(str(raw.get("sketch") or "").splitlines()[:25])
    return {
        "id": slugify(str(raw.get("id") or title)),
        "title": title, "pitch": str(raw.get("pitch") or "")[:200],
        "mcu": str(raw.get("mcu") or BOARDS[board]["name"])[:60],
        "sketch": sketch, "parts_list": pl, "board": board, "generated": True,
        "prompt": prompt[:200], "steps": steps,
    }


def parse_project(text: str, board: str, prompt: str = "") -> dict:
    return validate_project(_json.loads(repair_json(text)), board, prompt)


def is_generic_project(project: dict | None) -> bool:
    return bool(project) and project.get("id") != "blink"
