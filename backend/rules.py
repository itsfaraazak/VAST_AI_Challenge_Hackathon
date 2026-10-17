"""Deterministic checks over one segment caption. Stay quiet when a caption does not support a rule."""

from __future__ import annotations

import re

STEPS = (
    {"id": "led", "title": "Seat the LED across two rows"},
    {"id": "resistor", "title": "Drop in a 220Ω resistor"},
    {"id": "signal", "title": "Jump signal to Nano D13"},
    {"id": "gnd", "title": "Tie the cathode rail to GND"},
    {"id": "flash", "title": "Flash Blink and watch the beat"},
)

_LED = re.compile(r"\bleds?\b", re.I)
_RESISTOR = re.compile(r"\bresistor", re.I)
_SIGNAL = re.compile(r"\b(d\s*13|pin\s*13|jumper(?:\s+wires?)?|pins?)\b", re.I)
_GND = re.compile(r"\b(gnd|ground)\b", re.I)
_FLASH = re.compile(r"\b(arduino\s+ide|\bide\b|upload(?:ed|ing)?|blink(?:ing)?|sketch)\b", re.I)
_PIN = re.compile(r"\b(?:pin\s*|d\s*)(\d{1,2})\b", re.I)
_USB_CONNECTED = re.compile(
    r"\busb\b.{0,70}\b(?:connect\w*|plugg\w*)|\b(?:connect\w*|plugg\w*).{0,70}\busb\b",
    re.I,
)
_WIRING_CHANGE = re.compile(
    r"\b(inserting|inserted|manipulat\w*|adjust\w*|plugging in|connecting (?:it|them|a |the )|placing the jumper)\b",
    re.I,
)
_SHORT = re.compile(r"\bshort(?:ed|ing)?\b", re.I)
_FIVE_V = re.compile(r"\b5\s*v\b", re.I)
_COMPONENT_RULES = (
    ("Arduino Nano", re.compile(r"\b(arduino\s+nano|\bnano\b)\b", re.I)),
    ("breadboard", re.compile(r"\bbreadboard\b", re.I)),
    ("red LED", re.compile(r"\bred\s+led\b", re.I)),
    ("blue LED", re.compile(r"\bblue\s+led\b", re.I)),
    ("LED", _LED),
    ("resistor", _RESISTOR),
    ("USB cable", re.compile(r"\busb\b", re.I)),
    ("jumper wire", re.compile(r"\bjumper\b", re.I)),
    ("push button", re.compile(r"\b(push\s+button|button)\b", re.I)),
)
_CONNECTION = re.compile(
    r"\b(connect\w*|wired|wiring|in series|plugg\w*|insert\w*)\b",
    re.I,
)

SUPPORT = {
    "led": _LED,
    "resistor": _RESISTOR,
    "signal": _SIGNAL,
    "gnd": _GND,
    "flash": _FLASH,
}

WARN_COOLDOWN_SEC = 20.0


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text or "")
    return [part.strip() for part in parts if part.strip()]


def _absence(clause: str) -> bool:
    low = clause.lower().strip()
    if re.match(r"^(no|not|without|none|there are no|there is no)\b", low):
        return True
    if re.search(
        r"\b(does not|do not|did not|doesn't|don't|didn't|not show|not visible|not clearly visible|"
        r"no visible|without any|are not visible|is not visible|not seen|aren't any|isn't any)\b",
        low,
    ):
        return True
    return False


def mentions(text: str, pattern: re.Pattern) -> bool:
    for sentence in _sentences(text):
        clauses = re.split(r",\s+but\s+", sentence, flags=re.I)
        for clause in clauses:
            if _absence(clause):
                continue
            if pattern.search(clause):
                return True
    return False


def support_map(caption: str) -> dict[str, bool]:
    return {step["id"]: mentions(caption, SUPPORT[step["id"]]) for step in STEPS}


def usb_is_connected(caption: str) -> bool:
    return mentions(caption, _USB_CONNECTED)


def named_pins(caption: str) -> list[int]:
    found: set[int] = set()
    for sentence in _sentences(caption):
        clauses = re.split(r",\s+but\s+", sentence, flags=re.I)
        for clause in clauses:
            if _absence(clause):
                continue
            for raw in _PIN.findall(clause):
                number = int(raw)
                if number != 13:
                    found.add(number)
    return sorted(found)


def warnings_for(
    caption: str,
    time_sec: float,
    *,
    resistor_seen: bool,
    usb_connected: bool,
    signal_open: bool,
    last_warn_at: dict[str, float],
) -> list[dict]:
    alerts: list[dict] = []

    def allow(key: str) -> bool:
        previous = last_warn_at.get(key)
        if previous is None or time_sec < previous:
            return True
        return (time_sec - previous) >= WARN_COOLDOWN_SEC

    def add(key: str, text: str) -> None:
        if not allow(key):
            return
        last_warn_at[key] = time_sec
        alerts.append({"severity": "warning", "text": text, "speak": True})

    led = mentions(caption, _LED)
    resistor = mentions(caption, _RESISTOR)
    if led and not (resistor_seen or resistor):
        add(
            "led-no-resistor",
            "LED is in this segment and no resistor has shown up yet. Add the 220Ω before it stays on.",
        )
    if mentions(caption, _FIVE_V) and mentions(caption, _GND) and mentions(caption, _SHORT):
        add("short-5v-gnd", "This caption describes 5V shorted to GND. Unplug USB before continuing.")
    wiring = mentions(caption, _WIRING_CHANGE)
    usb_now = usb_connected or mentions(caption, _USB_CONNECTED)
    if wiring and usb_now:
        add(
            "usb-rewire",
            "Wiring is changing while USB is already connected. Unplug before moving jumpers.",
        )
    if signal_open:
        pins = named_pins(caption)
        if pins:
            listed = ", ".join(f"pin {number}" for number in pins)
            add(
                "wrong-pin",
                f"This segment names {listed}, not D13. Blink drives D13.",
            )
    return alerts


def circuit_from_caption(caption: str) -> dict:
    components: list[str] = []
    for label, pattern in _COMPONENT_RULES:
        if label == "LED" and ("red LED" in components or "blue LED" in components):
            continue
        if mentions(caption, pattern):
            components.append(label)
    connections: list[str] = []
    for sentence in _sentences(caption):
        clauses = re.split(r",\s+but\s+", sentence, flags=re.I)
        for clause in clauses:
            if _absence(clause) or not _CONNECTION.search(clause):
                continue
            text = re.sub(r"\s+", " ", clause).strip()
            if len(text) > 180:
                text = text[:177] + "..."
            if text not in connections:
                connections.append(text)
            if len(connections) >= 6:
                break
    return {"components": components, "connections": connections}


def merge_circuit(previous: dict | None, current: dict) -> dict:
    components: list[str] = []
    connections: list[str] = []
    for source in (previous, current):
        if not source:
            continue
        for item in source.get("components") or []:
            if item not in components:
                components.append(item)
        for item in source.get("connections") or []:
            if item not in connections:
                connections.append(item)
    return {"components": components, "connections": connections[:12]}


def diff_notes(older: dict | None, newer: dict | None) -> str:
    if not older or not newer:
        if newer:
            parts = ", ".join(newer.get("components") or []) or "nothing named yet"
            return f"Only one board note so far: {parts}."
        return "No board note yet."
    added_c = [item for item in newer["components"] if item not in older["components"]]
    removed_c = [item for item in older["components"] if item not in newer["components"]]
    added_n = [item for item in newer["connections"] if item not in older["connections"]]
    removed_n = [item for item in older["connections"] if item not in newer["connections"]]
    lines: list[str] = []
    if added_c:
        lines.append("Newly seen: " + ", ".join(added_c) + ".")
    if removed_c:
        lines.append("No longer in the note: " + ", ".join(removed_c) + ".")
    if added_n:
        lines.append("New connection: " + added_n[-1])
    if removed_n and not added_n:
        lines.append("A previous connection dropped out of the latest note.")
    if not lines:
        return "No new components or connections since the previous note."
    return " ".join(lines)
