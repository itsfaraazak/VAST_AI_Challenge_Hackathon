"""Generated projects + project memory (offline, LLM mocked)."""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import coach
import curriculum as cur
import projects_store


def good(board="nano"):
    p = "D5" if board == "nano" else "GPIO25"
    w1 = [{"from": p, "to": "R1.a"}, {"from": "R1.b", "to": "LED1.a"}]
    w2 = w1 + [{"from": "LED1.k", "to": "GND"}]
    st = lambda i, t, w: {"id": i, "title": t, "concept": "c", "action": "a", "teach": "t", "why": "w", "check": "", "hole_hint": "h",
                          "expect": {}, "pins": [p, "GND"], "wires": w, "parts": []}
    return {"id": "Traffic Light!", "title": "Traffic", "pitch": "p", "mcu": "x", "sketch": "void setup(){}",
            "parts_list": [{"type": "led", "qty": 3}], "steps": [st("a", "A", []), st("b", "B", w1), st("c", "C", w2)] * 3}


def sess():
    s = SimpleNamespace(twin=None, findings=[], coach=None, code="T")
    async def bc(_m): return None
    s.broadcast = bc
    return s


class Gen(unittest.TestCase):
    def test_valid_capped_and_unique(self):
        p = cur.validate_project(good(), "nano")
        self.assertEqual(len(p["steps"]), 7)
        self.assertEqual(len({s["id"] for s in p["steps"]}), 7)
        self.assertEqual(p["id"], "traffic-light")

    def test_esp32_pin_normalised_and_5v_rejected(self):
        p = cur.validate_project(good("esp32"), "esp32")
        self.assertEqual(p["steps"][1]["wires"][0]["from"], "GPIO25")
        bad = good("esp32"); bad["steps"][1]["wires"][0]["from"] = "5V"
        with self.assertRaises(ValueError): cur.validate_project(bad, "esp32")

    def test_bad_pin_short_and_no_resistor(self):
        for mut in (lambda g: g["steps"][1]["wires"].__setitem__(0, {"from": "D99", "to": "R1.a"}),
                    lambda g: g["steps"][1]["wires"].__setitem__(0, {"from": "GND", "to": "5V"}),
                    lambda g: g["steps"][1]["wires"].__setitem__(1, {"from": "D5", "to": "LED1.a"})):
            g = good(); mut(g)
            with self.assertRaises(ValueError): cur.validate_project(g, "nano")

    def test_led_without_resistor(self):
        g = good()
        for s in g["steps"]: s["wires"] = [{"from": "D5", "to": "LED1.a"}]
        with self.assertRaises(ValueError): cur.validate_project(g, "nano")

    def test_repair_truncated(self):
        txt = "```json\n" + json.dumps(good()) [:-40]
        try:
            cur.parse_project(txt, "nano")
        except ValueError:
            pass  # truncated into too few steps is acceptable; must not crash otherwise
        full = "```json\n" + json.dumps(good()) + "\n```"
        self.assertEqual(cur.parse_project(full, "nano")["board"], "nano")


class Flow(unittest.TestCase):
    def run_(self, c): return asyncio.run(c)

    def test_generate_and_state(self):
        s = sess()
        async def fake(sess_, http, system, user, **kw): return json.dumps(good()), {"source": "wandb"}
        with mock.patch.object(coach, "_llm", fake):
            st, note, ok = self.run_(coach.start_generated(s, None, "traffic light", "nano"))
        self.assertTrue(ok)
        self.assertEqual(st["project"]["id"], "traffic-light")
        self.assertEqual(len(st["project"]["steps"][1]["wires"]), 2)
        self.assertEqual(st["step_total"], 7)

    def test_fallback_blink(self):
        s = sess()
        async def fake(*a, **k): return "garbage", {}
        with mock.patch.object(coach, "_llm", fake):
            st, note, ok = self.run_(coach.start_generated(s, None, "x", "nano"))
        self.assertFalse(ok); self.assertEqual(st["project_id"], "blink"); self.assertIn("Blink", note)

    def test_converse_trigger_and_generic_diag(self):
        s = sess(); coach.ensure_session_coach(s)
        async def fake(sess_, http, system, user, **kw):
            return (json.dumps(good()) if "strict JSON" in system or "ONE strict" in system else ""), {"source": "wandb"}
        with mock.patch.object(coach, "_llm", fake):
            out = self.run_(coach.converse(s, None, "I want to build a traffic light with 3 LEDs"))
        self.assertEqual(s.coach["project_id"], "traffic-light")
        self.assertIn("custom project", out["text"])
        s.twin = {"components": [{"id": "d1", "type": "led"}], "nets": []}
        self.assertIsInstance(coach._diag(s), list)

    def test_snapshot_resume(self):
        s = sess(); coach.ensure_session_coach(s)
        coach.start_project(s, project=cur.validate_project(good(), "nano"), board="nano")
        coach.set_step(s, 3)
        s.coach["mistakes_log"] = [{"id": "led_reversed", "title": "the LED backwards"}]
        rec = projects_store.snapshot(s)
        self.assertEqual(rec["step_index"], 3)
        self.assertTrue(rec["key"].startswith("current-projects/traffic-light-"))
        s2 = sess(); coach.ensure_session_coach(s2)
        st = coach.resume_project(s2, rec)
        self.assertEqual(st["step_index"], 3)
        t = projects_store.resume_text(rec)
        self.assertIn("step 4", t); self.assertIn("backwards", t)
        self.assertEqual(projects_store.summarize(rec)["steps_total"], 7)


if __name__ == "__main__":
    unittest.main()
