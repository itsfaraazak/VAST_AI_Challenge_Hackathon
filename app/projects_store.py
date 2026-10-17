"""Digital-twin project memory persisted to VAST S3 (current-projects/<slug>-<ts>.json). Fails soft."""
from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy

from config import settings
from sponsors import vast_store

log = logging.getLogger("projects_store")
PREFIX = "current-projects/"


class _NullSess:
    async def broadcast(self, _msg) -> None:
        return None


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time()))


def parts_seen(sess) -> list[str]:
    twin = getattr(sess, "twin", None)
    seen = set((getattr(sess, "coach", None) or {}).get("parts_seen") or [])
    if isinstance(twin, dict):
        for c in twin.get("components") or []:
            if isinstance(c, dict) and c.get("type"):
                seen.add(str(c["type"]).lower())
    return sorted(seen)


def snapshot(sess) -> dict | None:
    """Build the persisted record from sess.coach (None if no project)."""
    import coach as C  # local import: avoid cycle
    c = getattr(sess, "coach", None)
    if not c or not c.get("project_id"):
        return None
    project = C._project(sess)
    if not project:
        return None
    c["parts_seen"] = parts_seen(sess)
    if not c.get("store_key"):
        c["store_key"] = f"{PREFIX}{project['id']}-{int(time.time())}.json"
    return {
        "key": c["store_key"], "title": project["title"], "prompt": project.get("prompt") or c.get("prompt") or "",
        "board": c.get("board", "nano"), "project": deepcopy(project), "step_index": c["step_index"],
        "steps_total": len(project["steps"]), "parts_seen": c["parts_seen"],
        "mistakes": list(c.get("mistakes_log") or [])[-30:], "updated_iso": _iso(),
        "sketch": c.get("sketch_text"),
    }


async def save(sess) -> dict:
    try:
        rec = snapshot(sess)
        if not rec:
            return {"ok": False, "reason": "no project"}
        return await vast_store.put_json(sess, rec["key"], rec)
    except Exception as e:  # noqa: BLE001
        log.warning("project save failed: %s", type(e).__name__)
        return {"ok": False, "reason": type(e).__name__}


def schedule_save(sess) -> None:
    """Fire-and-forget; safe from sync code and when no loop/S3 exists."""
    if not settings.s3_ready:
        return
    try:
        asyncio.get_running_loop().create_task(save(sess))
    except RuntimeError:
        pass


def summarize(rec: dict, modified: str = "") -> dict:
    total = int(rec.get("steps_total") or len((rec.get("project") or {}).get("steps") or []) or 0)
    idx = int(rec.get("step_index") or 0)
    # step_index is the current (0-based) step; finished steps = idx
    pct = round(100 * min(idx, total) / total) if total else 0
    return {"key": rec.get("key"), "title": rec.get("title"), "board": rec.get("board"), "step_index": idx,
            "steps_total": total, "updated": rec.get("updated_iso") or modified,
            "parts_seen": rec.get("parts_seen") or [], "pct": pct}


async def list_projects(sess=None, limit: int = 12) -> list[dict] | None:
    """Newest first; None if S3 unreachable."""
    sess = sess or _NullSess()
    objs = await vast_store.list_prefix(sess, PREFIX)
    if objs is None:
        return None
    objs.sort(key=lambda o: o.get("modified", ""), reverse=True)
    # latest object per slug-run is the same key (we overwrite one key per project run), so just load newest
    recs = await asyncio.gather(*[vast_store.get_json(sess, o["key"]) for o in objs[:limit]])
    items = [summarize(r, o["modified"]) for r, o in zip(recs, objs[:limit]) if isinstance(r, dict)]
    items.sort(key=lambda i: str(i.get("updated") or ""), reverse=True)
    return items


async def load(sess, key: str) -> dict | None:
    if not key.startswith(PREFIX) or ".." in key:
        return None
    rec = await vast_store.get_json(sess, key)
    return rec if isinstance(rec, dict) and rec.get("project") else None


def resume_text(rec: dict) -> str:
    project = rec["project"]
    steps = project.get("steps") or []
    idx = max(0, min(int(rec.get("step_index") or 0), len(steps) - 1))
    st = steps[idx] if steps else {}
    text = f"Welcome back, we were on step {idx + 1} of {len(steps)}: {st.get('title', '')}."
    ms = rec.get("mistakes") or []
    if ms:
        last = ms[-1]
        title = str(last.get("title") or last.get("id") or "a wiring slip").lower()
        text += f" I remember you had {title} last time, so double check that."
    seen = rec.get("parts_seen") or []
    if seen:
        text += f" Last time I saw: {', '.join(seen[:5])}."
    if st.get("action"):
        text += f" Next: {st['action']}"
    return text


async def seed_demo(http=None) -> str:
    """Seed 2 demo projects if the list is empty and S3 is reachable."""
    import curriculum as cur
    ok, why = await vast_store.check_s3()
    if not ok:
        return f"skip: {why}"
    existing = await list_projects()
    if existing is None or existing:
        return "skip: not empty" if existing else "skip: list failed"
    now = time.time()
    blink = cur.get_project("blink", board="nano")
    tl = _traffic_light()
    recs = [
        {"key": f"{PREFIX}blink-{int(now) - 3600}.json", "title": blink["title"], "prompt": "blink an LED", "board": "nano",
         "project": blink, "step_index": 3, "steps_total": len(blink["steps"]), "parts_seen": ["arduino", "breadboard", "led", "resistor"],
         "mistakes": [{"id": "led_reversed", "title": "the LED backwards", "step": 1, "ts": now - 3500}], "updated_iso": _iso(now - 3500)},
        {"key": f"{PREFIX}traffic-light-{int(now) - 600}.json", "title": tl["title"], "prompt": "traffic light with 3 LEDs", "board": "esp32",
         "project": tl, "step_index": 2, "steps_total": len(tl["steps"]), "parts_seen": ["esp32", "breadboard", "led"],
         "mistakes": [{"id": "resistor_missing", "title": "a missing series resistor", "step": 1, "ts": now - 500}], "updated_iso": _iso(now - 500)},
    ]
    sess = _NullSess()
    for r in recs:
        await vast_store.put_json(sess, r["key"], r)
    return "seeded 2"


def _traffic_light() -> dict:
    cols = [("red", "GPIO25", "R1", "LED1"), ("yellow", "GPIO26", "R2", "LED2"), ("green", "GPIO27", "R3", "LED3")]
    steps = [{"id": "orient", "title": "Seat the ESP32 and breadboard", "concept": "ESP32 GPIO pins are 3.3 V logic.",
              "action": "Straddle the ESP32 across the breadboard centre channel.", "teach": "We use GPIO25, 26, 27 and GND.",
              "why": "Each pin needs its own row.", "check": "", "hole_hint": "Leave a free row beside each GPIO.",
              "expect": {"has_board": True}, "pins": ["GPIO25", "GPIO26", "GPIO27", "GND"], "wires": [], "parts": ["esp32", "breadboard"]}]
    wires = []
    for n, (name, pin, r, l) in enumerate(cols):
        wires += [{"from": pin, "to": f"{r}.a", "color": "#c87941"}, {"from": f"{r}.b", "to": f"{l}.a", "color": "#d6ff4b"},
                  {"from": f"{l}.k", "to": "GND", "color": "#5b8def"}]
        steps.append({"id": f"{name}-led", "title": f"Wire the {name} LED", "concept": f"{name} LED through a 220 ohm resistor.",
                      "action": f"{pin} to a 220 ohm resistor to the {name} LED anode, cathode to GND.", "teach": "Always a series resistor.",
                      "why": "At 3.3 V and 220 ohm the current is about 6.8 mA, safe.", "check": "", "hole_hint": "Resistor and LED anode share a strip.",
                      "expect": {"types": ["led", "resistor"]}, "pins": [pin, "GND"], "wires": list(wires), "parts": ["led", "resistor"]})
    steps.append({"id": "run", "title": "Upload the sequence", "concept": "Cycle red, green, yellow.", "action": "Upload the sketch.",
                  "teach": "Check each LED polarity if one stays dark.", "why": "Timing is plain digitalWrite and delay.", "check": "",
                  "hole_hint": "USB into the DevKit.", "expect": {"complete": True}, "pins": ["GPIO25", "GPIO26", "GPIO27", "GND"],
                  "wires": list(wires), "parts": []})
    return {"id": "traffic-light", "title": "Traffic light - 3 LEDs on ESP32", "pitch": "Red, yellow and green LEDs cycling like a traffic light.",
            "mcu": "ESP32 DevKit (ESP32-WROOM)", "board": "esp32", "generated": True, "prompt": "traffic light with 3 LEDs",
            "sketch": "const int P[]={25,26,27};\nvoid setup(){for(int p:P)pinMode(p,OUTPUT);}\nvoid loop(){\n  for(int i=0;i<3;i++){digitalWrite(P[i],HIGH);delay(1000);digitalWrite(P[i],LOW);}\n}",
            "parts_list": [{"type": "led", "value": "red/yellow/green", "qty": 3}, {"type": "resistor", "value": "220", "qty": 3}],
            "steps": steps}
