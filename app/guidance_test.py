"""Gate tests: ungrounded LLM answers must be rejected."""
from __future__ import annotations

import unittest

from guidance import gate_message


class GateTests(unittest.TestCase):
    def test_accepts_grounded(self):
        findings = [{
            "id": "led_no_series_resistor",
            "severity": "critical",
            "rule": "LED_NO_SERIES_R",
            "message": "LED d1 has no series resistor.",
            "evidence": {"led": "d1"},
        }]
        ok, text = gate_message(
            "Add a series resistor before the LED.",
            {"led_no_series_resistor"},
            findings,
        )
        self.assertTrue(ok)
        self.assertTrue(text)

    def test_rejects_ungrounded_claim(self):
        findings = [{
            "id": "led_no_series_resistor",
            "severity": "critical",
            "rule": "LED_NO_SERIES_R",
            "message": "LED d1 has no series resistor.",
            "evidence": {"led": "d1"},
        }]
        ok, reason = gate_message(
            "Your capacitor C99 is 47uF and must be replaced immediately now.",
            {"led_no_series_resistor"},
            findings,
        )
        self.assertFalse(ok)
        self.assertIn(reason, ("ungrounded", "ungrounded_component"))

    def test_rejects_empty_without_ids(self):
        ok, reason = gate_message("Hello there friend", set(), [])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
