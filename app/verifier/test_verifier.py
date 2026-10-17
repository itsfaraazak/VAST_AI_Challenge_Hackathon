"""Unit tests for the deterministic verifier (>=8 cases)."""
from __future__ import annotations

import unittest

from verifier.engine import verify_twin


def twin(components, nets, supply=5.0):
    return {"components": components, "nets": nets, "supply_voltage": supply}


class VerifierTests(unittest.TestCase):
    def test_correct_led_circuit(self):
        t = twin(
            [
                {"id": "bat", "type": "battery", "value": "5"},
                {"id": "r1", "type": "resistor", "value": "220"},
                {"id": "d1", "type": "led", "value": "red"},
            ],
            [
                ["bat.pos", "r1.a"],
                ["r1.b", "d1.a"],
                ["d1.k", "bat.neg"],
            ],
        )
        r = verify_twin(t)
        rules = {f["rule"] for f in r["findings"]}
        self.assertNotIn("LED_NO_SERIES_R", rules)
        self.assertNotIn("LED_REVERSED", rules)
        self.assertNotIn("SUPPLY_SHORT", rules)
        self.assertIn(r["badge"], ("simulation-verified", "formally verified"))

    def test_no_resistor(self):
        t = twin(
            [
                {"id": "bat", "type": "battery", "value": "5"},
                {"id": "d1", "type": "led", "value": "red"},
            ],
            [["bat.pos", "d1.a"], ["d1.k", "bat.neg"]],
        )
        r = verify_twin(t)
        self.assertTrue(any(f["rule"] == "LED_NO_SERIES_R" for f in r["findings"]))

    def test_reversed_led(self):
        t = twin(
            [
                {"id": "bat", "type": "battery", "value": "5"},
                {"id": "r1", "type": "resistor", "value": "220"},
                {"id": "d1", "type": "led", "value": "red"},
            ],
            [
                ["bat.pos", "r1.a"],
                ["r1.b", "d1.k"],
                ["d1.a", "bat.neg"],
            ],
        )
        r = verify_twin(t)
        self.assertTrue(any(f["rule"] == "LED_REVERSED" for f in r["findings"]))

    def test_short(self):
        t = twin(
            [
                {"id": "bat", "type": "battery", "value": "5"},
                {"id": "r1", "type": "resistor", "value": "220"},
            ],
            [["bat.pos", "bat.neg"]],
        )
        r = verify_twin(t)
        self.assertTrue(any(f["rule"] == "SUPPLY_SHORT" for f in r["findings"]))

    def test_floating_net(self):
        t = twin(
            [
                {"id": "bat", "type": "battery", "value": "5"},
                {"id": "r1", "type": "resistor", "value": "220"},
                {"id": "d1", "type": "led", "value": "red"},
            ],
            [["bat.pos", "r1.a"], ["r1.b", "bat.neg"]],  # LED unused
        )
        r = verify_twin(t)
        self.assertTrue(any(f["rule"] == "FLOATING_NET" for f in r["findings"]))

    def test_z3_proof(self):
        # Large resistor → I < 20mA across [3,12]
        t = twin(
            [
                {"id": "bat", "type": "battery", "value": "5"},
                {"id": "r1", "type": "resistor", "value": "2200"},
                {"id": "d1", "type": "led", "value": "red"},
            ],
            [["bat.pos", "r1.a"], ["r1.b", "d1.a"], ["d1.k", "bat.neg"]],
        )
        r = verify_twin(t)
        z = r["z3"]
        if z and z.get("available"):
            self.assertTrue(z.get("proved"))
            self.assertEqual(r["badge"], "formally verified")
        else:
            self.skipTest("z3 unavailable")

    def test_z3_counterexample(self):
        # Small resistor → overcurrent at high V
        t = twin(
            [
                {"id": "bat", "type": "battery", "value": "5"},
                {"id": "r1", "type": "resistor", "value": "100"},
                {"id": "d1", "type": "led", "value": "red"},
            ],
            [["bat.pos", "r1.a"], ["r1.b", "d1.a"], ["d1.k", "bat.neg"]],
        )
        r = verify_twin(t)
        z = r["z3"]
        if z and z.get("available"):
            self.assertFalse(z.get("proved"))
            self.assertIsNotNone(z.get("counterexample_v"))
            self.assertEqual(r["badge"], "simulation-verified")
            self.assertNotEqual(r["badge"], "formally verified")
        else:
            self.skipTest("z3 unavailable")

    def test_invalid_twin(self):
        r = verify_twin({"nope": True})
        self.assertFalse(r["ok"])
        self.assertTrue(any(f["rule"] == "INVALID_TWIN" for f in r["findings"]))
        self.assertEqual(r["badge"], "simulation-verified")


if __name__ == "__main__":
    unittest.main(verbosity=2)
