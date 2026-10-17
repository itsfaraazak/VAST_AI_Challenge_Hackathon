"""Blink-on-Nano curriculum — technically correct wiring + teaching beats."""
from __future__ import annotations

from copy import deepcopy

# Canonical external Blink wiring (Arduino Nano, ATmega328):
#   D13 --[220Ω]-- LED anode (long) ; LED cathode (short) -- GND
# Built-in LED on D13 shares that pin; we teach an *external* LED on the breadboard.

BLINK_PROJECT = {
    "id": "blink",
    "title": "Blink — external LED on Arduino Nano",
    "pitch": "Wire one LED so pin D13 can blink it safely through a 220Ω resistor.",
    "mcu": "Arduino Nano (ATmega328)",
    "sketch": "File → Examples → 01.Basics → Blink (pin 13)",
    "steps": [
        {
            "id": "orient",
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

PROJECTS = {
    "blink": BLINK_PROJECT,
}


def list_projects() -> list[dict]:
    return [
        {"id": p["id"], "title": p["title"], "pitch": p["pitch"]}
        for p in PROJECTS.values()
    ]


def get_project(project_id: str) -> dict | None:
    p = PROJECTS.get(project_id)
    return deepcopy(p) if p else None


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
