import unittest

from perception.cosmos import _from_raw
from perception.twin_parse import TwinParseError


class CosmosParseTests(unittest.TestCase):
    def test_truncated_in_observation_keeps_parts(self):
        t = ('{"scene":"bench","observation":"A white breadboard holds a green Ard')
        with self.assertRaises(TwinParseError):  # bench with no parts is a useless frame -> retried
            _from_raw(t)

    def test_truncated_after_components_keeps_parts(self):
        t = ('{"scene":"bench","observation":"x","components":[{"id":"nano1","type":"arduino"},'
             '{"id":"d1","type":"led","value":"red"}],"led_lit":true,"issues":["a b c d')
        tw = _from_raw(t)
        self.assertEqual([c["type"] for c in tw["components"]], ["arduino", "led"])
        self.assertTrue(tw["led_lit"])

    def test_half_written_part_is_dropped(self):
        t = '```json\n{"scene":"bench","components":[{"id":"nano1","type":"arduino"},{"id":"r1","type":"res'
        self.assertEqual([c["type"] for c in _from_raw(t)["components"]], ["arduino"])

    def test_placeholder_nets_dropped(self):
        t = ('{"scene":"bench","components":[{"id":"nano1","type":"arduino"}],'
             '"nets":[["<partid>.<pin>","<partid>.<pin>"],["nano1.d13","r1.a"]],"issues":[]}')
        self.assertEqual(_from_raw(t)["nets"], [["nano1.d13", "r1.a"]])


if __name__ == "__main__":
    unittest.main()
