import asyncio, sys, os, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import settings
from sponsors import vast_store, registry, embed_memory


class Sess:
    code = "ABC123"; created = 0; findings = []; timings = []; twin = None; coach = None
    def __init__(self): self.msgs = []
    async def broadcast(self, m): self.msgs.append(m)


class T(unittest.TestCase):
    def test_store_disabled(self):
        with mock.patch.object(type(settings), "s3_ready", False):
            r = asyncio.run(vast_store.save_event(Sess(), "twin", {"a": 1}))
        self.assertFalse(r["ok"]); self.assertEqual(r["status"], "disabled")

    def test_store_saves_and_throttles(self):
        fake = mock.Mock()
        s = Sess()
        with mock.patch.object(type(settings), "s3_ready", True), mock.patch.object(vast_store, "_get_client", return_value=fake):
            r = asyncio.run(vast_store.save_event(s, "twin", {"a": 1}))
            r1 = asyncio.run(vast_store.save_event(s, "frame", b"x"))
            r2 = asyncio.run(vast_store.save_event(s, "frame", b"x"))
        self.assertTrue(r["ok"]); self.assertTrue(r["key"].startswith("current-live/ABC123/"))
        self.assertTrue(r1["ok"]); self.assertEqual(r2["status"], "throttled")
        self.assertEqual(fake.put_object.call_count, 2)
        self.assertTrue(any(m["sponsor"] == "vast" for m in s.msgs))

    def test_store_error_soft(self):
        fake = mock.Mock(); fake.put_object.side_effect = RuntimeError("x")
        with mock.patch.object(type(settings), "s3_ready", True), mock.patch.object(vast_store, "_get_client", return_value=fake):
            r = asyncio.run(vast_store.save_event(Sess(), "twin", {}))
        self.assertEqual(r["status"], "error")

    def test_registry(self):
        async def ok(*a, **k): return True, "HTTP 200"
        with mock.patch.object(registry, "_get", ok), mock.patch.object(vast_store, "check_s3", ok):
            r = asyncio.run(registry.sponsor_status(None))
        ids = {t["id"] for t in r["tools"]}
        self.assertTrue({"cosmos3", "yolo11", "canary", "embed1", "wandb", "vast_s3", "vast_vss", "coreweave", "cursor"} <= ids)
        for t in r["tools"]:
            self.assertEqual(set(t), {"id", "sponsor", "name", "role", "ok", "detail"})

    def test_recall(self):
        vecs = iter([[1.0, 0.0], [0.99, 0.05], [0.0, 1.0]])
        async def fake(http, text): return next(vecs)
        s = Sess()
        with mock.patch.object(embed_memory, "embed", fake):
            self.assertTrue(asyncio.run(embed_memory.remember(s, "led reversed", http=object())))
            self.assertIsNotNone(asyncio.run(embed_memory.recall(s, "led backwards", http=object())))
            self.assertIsNone(asyncio.run(embed_memory.recall(s, "no resistor", http=object())))

if __name__ == "__main__": unittest.main()
