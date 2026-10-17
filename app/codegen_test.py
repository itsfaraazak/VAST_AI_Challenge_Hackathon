import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import codegen
import mcp_server

HERE = Path(__file__).parent


def ctx(board="nano", pins=None, res=True):
    return {"board": board, "project": {"id": "blink", "title": "Blink"}, "step_index": 4, "pins": pins or [],
            "parts_seen": [], "parts": [], "has_resistor": res}


class ValidatorTests(unittest.TestCase):
    def test_templates_valid_both_boards(self):
        for b in ("nano", "esp32"):
            for instr in (None, "fade the LED", "button toggles it", "beep", "blink twice as fast", "use pin 8"):
                code = codegen.fallback_sketch(ctx(b), instr)
                ok, probs, _ = codegen.validate(code, b)
                self.assertTrue(ok, (b, instr, probs))
                self.assertLessEqual(len(code.splitlines()), 60)

    def test_instruction_effects(self):
        self.assertIn("HALF_PERIOD = 500", codegen.fallback_sketch(ctx(), "blink twice as fast"))
        self.assertIn("LED_PIN = 8", codegen.fallback_sketch(ctx(), "use pin 8"))
        self.assertIn("ledcAttach", codegen.fallback_sketch(ctx("esp32"), "fade"))
        self.assertIn("analogWrite", codegen.fallback_sketch(ctx("nano"), "fade"))

    def test_rejects(self):
        self.assertFalse(codegen.validate("void setup(){", "nano")[0])
        self.assertFalse(codegen.validate("void setup(){}", "nano")[0])
        bad = "void setup(){pinMode(30,OUTPUT);}\nvoid loop(){delay(99999);}"
        p = codegen.validate(bad, "nano")[1]
        self.assertTrue(any("pin 30" in x for x in p) and any("delay" in x for x in p))
        self.assertFalse(codegen.validate("void setup(){pinMode(7,OUTPUT);}\nvoid loop(){}", "esp32")[0])  # flash pin
        self.assertFalse(codegen.validate("void setup(){pinMode(2,OUTPUT);ledcAttach(2,5000,8);}\nvoid loop(){}", "nano")[0])

    def test_resistor_note(self):
        _, _, notes = codegen.validate(codegen.fallback_sketch(ctx()), "nano", has_resistor=False)
        self.assertTrue(any("resistor" in n for n in notes))

    def test_pin_helpers(self):
        self.assertEqual(codegen.pin_num("D5", "nano"), 5)
        self.assertEqual(codegen.pin_num("GPIO25", "esp32"), 25)
        self.assertIsNone(codegen.pin_num("R1.a", "nano"))


class McpTests(unittest.TestCase):
    def test_tools_list_stdio(self):
        env = {**os.environ, "CURRENT_MCP_MINIMAL": "1"}
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        r = subprocess.run([sys.executable, str(HERE / "mcp_server.py")], input="\n".join(map(json.dumps, reqs)) + "\n",
                           capture_output=True, text=True, env=env, timeout=20)
        lines = [json.loads(x) for x in r.stdout.splitlines()]
        names = {t["name"] for t in lines[1]["result"]["tools"]}
        self.assertEqual(names, {"current_get_state", "current_get_sketch", "current_update_sketch",
                                 "current_list_projects", "current_resume_project", "current_get_twin"})

    def test_sdk_tools_list(self):
        try:
            import mcp  # noqa: F401
        except Exception:  # noqa: BLE001
            self.skipTest("mcp sdk missing")
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def go():
            p = StdioServerParameters(command=sys.executable, args=[str(HERE / "mcp_server.py")])
            async with stdio_client(p) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    return {t.name for t in (await s.list_tools()).tools}
        self.assertIn("current_get_state", asyncio.run(go()))


if __name__ == "__main__":
    unittest.main()
