"""Wokwi Blink world-model: diagram + sketch + connectivity advice.

Shared JSON contract used by CURRENT and ElectronicAI.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from typing import Any

GOAL_BLINK = "arduino_nano_blink"

_SKETCH = """\
// CURRENT — Blink on Nano D13
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
  Serial.println("CURRENT Blink ready");
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(500);
  digitalWrite(LED_BUILTIN, LOW);
  delay(500);
}
"""

_PARTS_BASE = [
    {"type": "wokwi-breadboard-half", "id": "bb1", "top": -50, "left": -80, "attrs": {}},
    {"type": "wokwi-arduino-nano", "id": "nano", "top": 70, "left": 20, "rotate": 90, "attrs": {}},
    {"type": "wokwi-led", "id": "led1", "top": -20, "left": 220, "attrs": {"color": "red"}},
]

_RESISTOR_PART = {
    "type": "wokwi-resistor",
    "id": "r1",
    "top": -10,
    "left": 150,
    "rotate": 90,
    "attrs": {"value": "220"},
}


def _good_connections() -> list[list]:
    return [
        ["nano:13", "r1:1", "green", ["v0"]],
        ["r1:2", "led1:A", "green", ["v1"]],
        ["led1:C", "nano:GND.2", "black", ["v2"]],
    ]


def _broken_no_resistor() -> list[list]:
    return [
        ["nano:13", "led1:A", "red", ["v0"]],
        ["led1:C", "nano:GND.2", "black", ["v1"]],
    ]


def _broken_wrong_pin() -> list[list]:
    return [
        ["nano:8", "r1:1", "orange", ["v0"]],
        ["r1:2", "led1:A", "green", ["v1"]],
        ["led1:C", "nano:GND.2", "black", ["v2"]],
    ]


def _broken_open_gnd() -> list[list]:
    return [
        ["nano:13", "r1:1", "green", ["v0"]],
        ["r1:2", "led1:A", "green", ["v1"]],
    ]


def _diagram(parts: list[dict], connections: list[list]) -> str:
    payload = {
        "version": 1,
        "author": "CURRENT",
        "editor": "wokwi",
        "parts": parts,
        "connections": connections,
        "dependencies": {},
    }
    return json.dumps(payload, indent=2)


def _flags_from_circuit(circuit: dict | None) -> dict[str, bool]:
    circuit = circuit or {}
    components = [str(c).lower() for c in (circuit.get("components") or [])]
    connections = " ".join(str(c).lower() for c in (circuit.get("connections") or []))
    blob = " ".join(components) + " " + connections

    has_led = any("led" in c for c in components) or bool(re.search(r"\bled\b", blob))
    has_resistor = any("resistor" in c for c in components) or "220" in blob
    has_nano = any("nano" in c or "arduino" in c for c in components) or "nano" in blob
    has_gnd = bool(re.search(r"\b(gnd|ground)\b", blob))
    has_signal = bool(re.search(r"\b(d\s*13|pin\s*13|signal)\b", blob))
    wrong_pin = bool(re.search(r"\b(d\s*[0-9]+|pin\s*[0-9]+)\b", blob)) and not has_signal
    if re.search(r"\b(d\s*8|pin\s*8|d\s*9|pin\s*9|d\s*10|pin\s*10)\b", blob) and not has_signal:
        wrong_pin = True

    # Empty note → known-good template so the user can always open a working sim.
    if not components and not connections.strip():
        return {
            "has_led": True,
            "has_resistor": True,
            "has_nano": True,
            "has_gnd": True,
            "has_signal": True,
            "wrong_pin": False,
            "empty": True,
        }

    return {
        "has_led": has_led,
        "has_resistor": has_resistor,
        "has_nano": has_nano or True,
        "has_gnd": has_gnd,
        "has_signal": has_signal,
        "wrong_pin": wrong_pin,
        "empty": False,
    }


def _build_project(flags: dict[str, bool]) -> tuple[dict[str, str], list[dict], list[dict]]:
    parts = copy.deepcopy(_PARTS_BASE)
    issues: list[dict] = []
    next_actions: list[dict] = []

    if flags.get("empty"):
        parts.append(copy.deepcopy(_RESISTOR_PART))
        files = {
            "diagram.json": _diagram(parts, _good_connections()),
            "sketch.ino": _SKETCH,
        }
        return files, issues, next_actions

    if not flags.get("has_led"):
        issues.append(
            {
                "id": "missing_led",
                "severity": "critical",
                "text": "No LED seen on the bench note yet.",
            }
        )
        next_actions.append({"id": "add_led", "label": "Seat the LED across two breadboard rows"})

    use_resistor = bool(flags.get("has_resistor"))
    if use_resistor:
        parts.append(copy.deepcopy(_RESISTOR_PART))
    else:
        issues.append(
            {
                "id": "no_series_resistor",
                "severity": "critical",
                "text": "LED path has no series resistor — risk of frying the diode.",
            }
        )
        next_actions.append({"id": "add_resistor", "label": "Add a 220Ω resistor in series with the LED"})

    if flags.get("wrong_pin"):
        issues.append(
            {
                "id": "wrong_pin",
                "severity": "warning",
                "text": "Signal looks tied to a pin other than D13; Blink drives LED_BUILTIN (13).",
            }
        )
        next_actions.append({"id": "move_signal_to_d13", "label": "Move the signal jumper to Nano D13"})

    if not flags.get("has_gnd"):
        issues.append(
            {
                "id": "open_gnd",
                "severity": "critical",
                "text": "Cathode / GND return is not confirmed — the LED loop is open.",
            }
        )
        next_actions.append({"id": "tie_gnd", "label": "Tie the LED cathode rail to Nano GND"})

    if not flags.get("has_signal") and not flags.get("wrong_pin"):
        issues.append(
            {
                "id": "missing_signal",
                "severity": "warning",
                "text": "No D13 / signal jumper confirmed yet.",
            }
        )
        next_actions.append({"id": "add_signal_d13", "label": "Jump Nano D13 to the LED anode side"})

    if flags.get("wrong_pin") and use_resistor:
        connections = _broken_wrong_pin()
    elif not use_resistor:
        connections = _broken_no_resistor()
    elif not flags.get("has_gnd"):
        connections = _broken_open_gnd()
    else:
        connections = _good_connections()

    files = {
        "diagram.json": _diagram(parts, connections),
        "sketch.ino": _SKETCH,
    }
    return files, issues, next_actions


def _netlist(flags: dict[str, bool], issues: list[dict]) -> dict:
    components = ["Arduino Nano", "LED"]
    if flags.get("has_resistor") or flags.get("empty"):
        components.append("220Ω resistor")
    nets = []
    if flags.get("empty") or (flags.get("has_signal") and flags.get("has_resistor") and flags.get("has_gnd")):
        nets = [
            {"name": "signal", "nodes": ["nano:D13", "R220", "LED:A"]},
            {"name": "return", "nodes": ["LED:C", "nano:GND"]},
        ]
    else:
        if flags.get("has_signal") or flags.get("wrong_pin"):
            nets.append({"name": "signal", "nodes": ["nano:Dx", "LED:A"]})
        if flags.get("has_gnd"):
            nets.append({"name": "return", "nodes": ["LED:C", "nano:GND"]})
    return {"components": components, "nets": nets, "issue_ids": [i["id"] for i in issues]}


def _advice_text(ok: bool, issues: list[dict], next_actions: list[dict], question: str) -> str:
    if ok:
        if re.search(r"will it work|simulate|wokwi", question or "", re.I):
            return "Sim says the Blink loop is closed: D13 → 220Ω → LED → GND. It should blink."
        return "Circuit looks complete for Blink. Next: flash the sketch and watch D13."
    if next_actions:
        first = next_actions[0]["label"]
        top = issues[0]["text"] if issues else "Something is incomplete."
        return f"{top} Sim next step: {first}."
    if issues:
        return issues[0]["text"]
    return "Sim has no clear next step yet — sync from the bench and ask again."


def advise(
    circuit_note: dict | None = None,
    goal: str = GOAL_BLINK,
    question: str = "",
    flags_override: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Return the shared advise JSON (files, issues, next_actions, advice)."""
    goal = goal or GOAL_BLINK
    flags = flags_override if flags_override is not None else _flags_from_circuit(circuit_note)
    files, issues, next_actions = _build_project(flags)
    ok = len(issues) == 0
    return {
        "ok": ok,
        "goal": goal,
        "issues": issues,
        "next_actions": next_actions,
        "netlist": _netlist(flags, issues),
        "files": files,
        "advice": _advice_text(ok, issues, next_actions, question),
        "flags": flags,
        "embed": {
            "src": "https://wokwi.com/experimental/embed",
            "firmware": "sketch.ino",
            "elf": "sketch.ino",
        },
    }


def apply_action(action_id: str, circuit_note: dict | None = None) -> dict[str, Any]:
    """Mutate flags as if the user applied a fix, then re-advise."""
    flags = _flags_from_circuit(circuit_note)
    flags["empty"] = False
    if action_id == "add_resistor":
        flags["has_resistor"] = True
    elif action_id == "move_signal_to_d13" or action_id == "add_signal_d13":
        flags["has_signal"] = True
        flags["wrong_pin"] = False
    elif action_id == "tie_gnd":
        flags["has_gnd"] = True
    elif action_id == "add_led":
        flags["has_led"] = True
    elif action_id == "make_good":
        flags = {
            "has_led": True,
            "has_resistor": True,
            "has_nano": True,
            "has_gnd": True,
            "has_signal": True,
            "wrong_pin": False,
            "empty": True,
        }
    return advise(circuit_note=circuit_note, flags_override=flags, question="applied " + action_id)


class SimState:
    """In-memory sim project for one CURRENT server process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.circuit: dict = {"components": [], "connections": []}
        self.last: dict = advise(self.circuit)

    def snapshot(self) -> dict:
        with self._lock:
            out = copy.deepcopy(self.last)
            out["circuit"] = copy.deepcopy(self.circuit)
            return out

    def sync(self, circuit: dict | None) -> dict:
        with self._lock:
            self.circuit = {
                "components": list((circuit or {}).get("components") or []),
                "connections": list((circuit or {}).get("connections") or []),
            }
            self.last = advise(self.circuit)
            out = copy.deepcopy(self.last)
            out["circuit"] = copy.deepcopy(self.circuit)
            return out

    def advise(self, question: str = "", goal: str = GOAL_BLINK) -> dict:
        with self._lock:
            self.last = advise(self.circuit, goal=goal, question=question)
            out = copy.deepcopy(self.last)
            out["circuit"] = copy.deepcopy(self.circuit)
            return out

    def apply(self, action_id: str) -> dict:
        with self._lock:
            self.last = apply_action(action_id, self.circuit)
            # Reflect applied fixes into the light circuit note so sync stays consistent.
            comps = list(self.circuit.get("components") or [])
            conns = list(self.circuit.get("connections") or [])
            if action_id == "add_resistor" and "Resistor" not in comps:
                comps.append("Resistor")
            if action_id in ("move_signal_to_d13", "add_signal_d13"):
                if "Arduino Nano" not in comps:
                    comps.append("Arduino Nano")
                conns.append("signal wire to Nano D13")
            if action_id == "tie_gnd":
                conns.append("LED cathode to Nano GND")
            if action_id == "add_led" and "LED" not in comps:
                comps.append("LED")
            if action_id == "make_good":
                comps = ["Arduino Nano", "LED", "Resistor"]
                conns = ["D13 through 220Ω to LED anode", "LED cathode to GND"]
            self.circuit = {"components": comps, "connections": conns}
            out = copy.deepcopy(self.last)
            out["circuit"] = copy.deepcopy(self.circuit)
            return out


# Module-level helpers for ElectronicAI tool use without SimState.
__all__ = ["advise", "apply_action", "SimState", "GOAL_BLINK"]
