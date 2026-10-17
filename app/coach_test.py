"""Tests for mistake detection and proactive coach (stdlib unittest, offline)."""
from __future__ import annotations

import asyncio
import time
import unittest
from types import SimpleNamespace

import coach
from curriculum import get_project
from mistakes import diagnose


def tw(comps, nets, **kw):
    t = {"components": [{"id": i, "type": ty} for i, ty in comps], "nets": nets, "observation": "", "placements": []}
    t.update(kw)
    return t


def ids(twin, findings=None):
    return {m["id"] for m in diagnose(twin, findings, None)}


GOOD = tw([("nano", "arduino"), ("r1", "resistor"), ("d1", "led")],
          [["nano.D13", "r1.a"], ["r1.b", "d1.a"], ["d1.k", "nano.GND"]])


class MistakeTests(unittest.TestCase):
    def test_good_circuit_clean(self):
        self.assertEqual(ids(GOOD), set())

    def test_none_twin(self):
        self.assertEqual(diagnose(None, None, None), [])
        self.assertEqual(diagnose({}, [], None), [])

    def test_led_reversed(self):
        t = tw([("nano", "arduino"), ("r1", "resistor"), ("d1", "led")],
               [["nano.D13", "r1.a"], ["r1.b", "d1.k"], ["d1.a", "nano.GND"]])
        self.assertIn("led_reversed", ids(t))

    def test_resistor_missing(self):
        t = tw([("nano", "arduino"), ("d1", "led")], [["nano.D13", "d1.a"], ["d1.k", "nano.GND"]])
        self.assertIn("resistor_missing", ids(t))

    def test_resistor_to_5v(self):
        t = tw([("nano", "arduino"), ("r1", "resistor"), ("d1", "led")],
               [["nano.5V", "r1.a"], ["r1.b", "d1.a"], ["d1.k", "nano.GND"]])
        self.assertIn("resistor_to_5v", ids(t))

    def test_gnd_missing(self):
        t = tw([("nano", "arduino"), ("r1", "resistor"), ("d1", "led")],
               [["nano.D13", "r1.a"], ["r1.b", "d1.a"]])
        self.assertIn("gnd_missing", ids(t))

    def test_3v3_instead_of_d13(self):
        t = tw([("nano", "arduino"), ("r1", "resistor"), ("d1", "led")],
               [["nano.3V3", "r1.a"], ["r1.b", "d1.a"], ["d1.k", "nano.GND"]])
        self.assertIn("used_3v3_not_signal", ids(t))

    def test_not_same_strip(self):
        t = tw([("nano", "arduino"), ("r1", "resistor"), ("d1", "led")],
               [["nano.D13", "r1.a"], ["d1.k", "nano.GND"]])
        self.assertIn("not_same_strip", ids(t))

    def test_legs_shorted(self):
        t = tw([("nano", "arduino"), ("r1", "resistor"), ("d1", "led")],
               [["nano.D13", "r1.a", "r1.b"], ["r1.b", "d1.a"], ["d1.k", "nano.GND"]])
        self.assertIn("legs_shorted", ids(t))

    def test_usb_and_straddle_from_wiring_check(self):
        t = dict(GOOD, wiring_check={"usb": "not connected", "note": "nano does not straddle the center channel"})
        r = ids(t)
        self.assertIn("usb_missing", r)
        self.assertIn("board_straddle", r)

    def test_finding_ids(self):
        r = ids(None, [{"id": "led_reversed", "message": "x"}, {"id": "led_overcurrent", "message": "y"}])
        self.assertEqual(r, {"led_reversed", "led_overcurrent"})


def sess():
    return SimpleNamespace(twin=None, findings=[], coach=None)


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


class GroundingTests(unittest.TestCase):
    def test_fail_soft_without_vss(self):
        import asyncio
        from history import grounding_examples
        self.assertEqual(asyncio.run(grounding_examples(None, "Blink", "LED")), [])


class CoachTests(unittest.TestCase):
    def test_boards(self):
        self.assertEqual(get_project("blink")["steps"][0]["pins"][0], "D13")
        e = get_project("blink", board="esp32")
        self.assertIn("GPIO2", e["steps"][2]["action"])
        for s in e["steps"]:
            self.assertTrue(s["why"] and s["check"] and s["hole_hint"])

    def test_start_esp32_and_state(self):
        s = sess()
        st = coach.start_project(s, "blink", board="esp32")
        self.assertEqual(st["board"], "esp32")
        self.assertIn("mistakes", st)
        self.assertEqual(coach.public_coach_state(s)["mistakes"], [])

    def test_tick_mistake_then_idle_hints(self):
        s = sess()
        coach.start_project(s, "blink")
        s.twin = tw([("nano", "arduino"), ("d1", "led")], [["nano.D13", "d1.a"], ["d1.k", "nano.GND"]])
        s.last_cosmos_ts = 1.0
        self.assertIsNone(run(coach.tick(s, None)))  # one analysis is not enough: nets wobble
        s.last_cosmos_ts = 2.0  # second consecutive analysis agrees
        m = run(coach.tick(s, None))
        self.assertEqual(m["finding_ids"], ["resistor_missing"])
        self.assertIsNone(run(coach.tick(s, None)))  # not repeated
        self.assertEqual(s.coach["spoken_mistakes"], ["resistor_missing@0"])
        s.twin = None
        s.coach["last_act_ts"] = time.time() - 30
        h1 = run(coach.tick(s, None))
        self.assertEqual(h1["hint_level"], 1)
        s.coach["last_hint_ts"] = 0
        h2 = run(coach.tick(s, None))
        s.coach["last_hint_ts"] = 0
        h3 = run(coach.tick(s, None))
        self.assertEqual(h3["hint_level"], 3)
        self.assertIn("Exactly", h3["text"])

    def test_celebrate_and_quiz(self):
        s = sess()
        coach.start_project(s, "blink")
        s.twin = tw([("nano", "arduino")], [])
        s.last_cosmos_ts = 1.0
        self.assertIsNone(run(coach.on_twin_update(s, None)))  # one twin is not enough
        s.last_cosmos_ts = 2.0
        out = run(coach.on_twin_update(s, None))
        self.assertTrue(out["step_ready"])
        self.assertIn("Ready for the next step", out["text"])
        self.assertEqual(s.coach["step_index"], 0)  # asked, did not auto-advance
        self.assertTrue(s.coach["awaiting_next"])
        yes = run(coach.converse(s, None, "yes"))
        self.assertEqual(s.coach["step_index"], 1)
        self.assertFalse(s.coach["awaiting_next"])
        self.assertTrue(yes["text"])


if __name__ == "__main__":
    unittest.main()
