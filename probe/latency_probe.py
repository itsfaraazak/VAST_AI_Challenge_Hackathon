#!/usr/bin/env python3
"""Latency probe for the live-twin loop. Stdlib only. Run on the workshop VM.

Tests the hypothesis: a 2-4 s perception loop is possible by calling the shared
GPU endpoints directly (Cosmos3-Reason, YOLO11, Embed1, Canary-1B).

Usage:
  python3 latency_probe.py [--video clip.mp4] [-n 5] [--conc 4] [--out results.json]

Env (already set on the VM; names only, never printed):
  COSMOS3_REASON_URL YOLO_URL COSMOS_EMBED1_URL CANARY_1B_URL GPU_BEARER_TOKEN
If GPU_BEARER_TOKEN is unset, it is read from the single /config/*.config file.
Without --video, a synthetic clip is generated with ffmpeg (if installed).
"""
import argparse, base64, glob, io, json, math, os, shutil, statistics as st
import struct, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error, wave


def load_env():
    if os.environ.get("GPU_BEARER_TOKEN"):
        return
    files = glob.glob("/config/*.config")
    if len(files) != 1:
        sys.exit("GPU_BEARER_TOKEN unset and /config/*.config not unique")
    for line in open(files[0]):
        k, _, v = line.strip().partition("=")
        if k in ("GPU_BEARER_TOKEN", "COSMOS3_REASON_URL", "YOLO_URL",
                 "COSMOS_EMBED1_URL", "CANARY_1B_URL") and not os.environ.get(k):
            os.environ[k] = v


def req(url, body=None, headers=None, timeout=120, raw=False):
    h = {"Authorization": f"Bearer {os.environ['GPU_BEARER_TOKEN']}"}
    h.update(headers or {})
    r = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp if raw else resp.read()


def jpost(url, obj, **kw):
    return req(url, json.dumps(obj).encode(), {"Content-Type": "application/json"}, **kw)


def timed(fn):
    t = time.perf_counter()
    try:
        fn()
        return time.perf_counter() - t, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:160]!r}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def make_media(video, tmp):
    """Return dict of {name: bytes} for clips (2s, 4s) and a jpeg frame."""
    ff = shutil.which("ffmpeg")
    out = {}
    if video:
        src = video
    elif ff:
        src = os.path.join(tmp, "src.mp4")
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=640x360:rate=15", "-t", "6", "-pix_fmt",
                        "yuv420p", src], check=True)
    else:
        sys.exit("need --video or ffmpeg")
    if not ff:
        sys.exit("ffmpeg required to cut clips/frames")
    for name, secs in (("clip2", 2), ("clip4", 4)):
        p = os.path.join(tmp, name + ".mp4")
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-t", str(secs),
                        "-vf", "scale=640:-2", "-an", "-pix_fmt", "yuv420p", p], check=True)
        out[name] = open(p, "rb").read()
    p = os.path.join(tmp, "f.jpg")
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-frames:v", "1",
                    "-vf", "scale=640:-2", p], check=True)
    out["frame"] = open(p, "rb").read()
    return out


def tone_wav(secs=3, rate=16000):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
                               for i in range(secs * rate)))
    return b.getvalue()


def multipart(fields, fname, data):
    bd = "----probe"
    parts = []
    for k, v in fields.items():
        parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
                 f'Content-Type: audio/wav\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{bd}--\r\n".encode())
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={bd}"}


def b64(b):
    return base64.b64encode(b).decode()


TWIN_PROMPT = ("List the electronic components visible and how they are connected as JSON "
               '{"components":[{"id":"","type":""}],"nets":[["id.pin","id.pin"]]}. JSON only.')
SHORT_PROMPT = "In one short sentence, what is happening?"


def build_tests(m, model, embed_model):
    cr = os.environ["COSMOS3_REASON_URL"].rstrip("/")

    def chat(content, max_tokens, stream=False):
        return {"model": model, "temperature": 0, "max_tokens": max_tokens, "stream": stream,
                "messages": [{"role": "user", "content": content}]}

    def vid(clip):
        return {"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + b64(m[clip])}}

    def img():
        return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64(m["frame"])}}

    def ttft(content, max_tokens):
        def f():
            resp = jpost(cr + "/v1/chat/completions", chat(content, max_tokens, True), raw=True)
            for line in resp:
                if line.startswith(b"data:") and b"[DONE]" not in line and b'"content"' in line:
                    break
            resp.close()
        return f

    T = {}
    T["cosmos text-only 16tok (baseline)"] = lambda: jpost(
        cr + "/v1/chat/completions", chat("Reply with: OK", 16))
    T["cosmos IMAGE short 48tok"] = lambda: jpost(
        cr + "/v1/chat/completions", chat([{"type": "text", "text": SHORT_PROMPT}, img()], 48))
    T["cosmos IMAGE twin-json 256tok"] = lambda: jpost(
        cr + "/v1/chat/completions", chat([{"type": "text", "text": TWIN_PROMPT}, img()], 256))
    T["cosmos CLIP2s short 48tok"] = lambda: jpost(
        cr + "/v1/chat/completions", chat([{"type": "text", "text": SHORT_PROMPT}, vid("clip2")], 48))
    T["cosmos CLIP4s twin-json 256tok"] = lambda: jpost(
        cr + "/v1/chat/completions", chat([{"type": "text", "text": TWIN_PROMPT}, vid("clip4")], 256))
    T["cosmos IMAGE time-to-first-token"] = ttft(
        [{"type": "text", "text": TWIN_PROMPT}, img()], 256)
    if os.environ.get("YOLO_URL"):
        y = os.environ["YOLO_URL"].rstrip("/")
        T["yolo CLIP2s"] = lambda: jpost(y + "/v1/infer", {
            "video_base64": b64(m["clip2"]), "filename": "c.mp4", "include_frames": False})
    if os.environ.get("COSMOS_EMBED1_URL"):
        e = os.environ["COSMOS_EMBED1_URL"].rstrip("/")
        T["embed1 text"] = lambda: jpost(e + "/v1/embeddings", {
            "input": "led wired backwards", "model": embed_model,
            "request_type": "query", "encoding_format": "float"})
        T["embed1 CLIP2s"] = lambda: jpost(e + "/v1/embeddings", {
            "input": "data:video/mp4;base64," + b64(m["clip2"]), "model": embed_model,
            "request_type": "query", "encoding_format": "float"})
    if os.environ.get("CANARY_1B_URL"):
        c = os.environ["CANARY_1B_URL"].rstrip("/")
        body, hd = multipart({"model": "nvidia/canary-1b"}, "a.wav", tone_wav(3))
        T["canary ASR 3s wav"] = lambda: req(c + "/v1/audio/transcriptions", body, hd)
    return T


def model_id(url):
    d = json.loads(req(url.rstrip("/") + "/v1/models"))
    return d["data"][0]["id"]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def run(name, fn, n, conc):
    lat, errs = [], []
    lock = threading.Lock()

    def worker(k):
        for _ in range(k):
            d, e = timed(fn)
            with lock:
                (lat if d is not None else errs).append(d if d is not None else e)

    per = max(1, n // conc)
    ts = [threading.Thread(target=worker, args=(per,)) for _ in range(conc)]
    wall = time.perf_counter()
    [t.start() for t in ts]; [t.join() for t in ts]
    wall = time.perf_counter() - wall
    row = {"test": name, "conc": conc, "ok": len(lat), "err": len(errs), "wall_s": round(wall, 2)}
    if lat:
        row.update(p50=round(st.median(lat), 2), p95=round(pct(lat, .95), 2),
                   min=round(min(lat), 2), max=round(max(lat), 2))
    if errs:
        row["first_err"] = errs[0]
    return row


def verdict(rows):
    tgt = {"cosmos IMAGE short 48tok": 3.0, "cosmos IMAGE twin-json 256tok": 6.0}
    out = []
    for r in rows:
        if r["conc"] == 1 and r["test"] in tgt and "p50" in r:
            out.append(f'{r["test"]}: p50 {r["p50"]}s vs target {tgt[r["test"]]}s -> '
                       f'{"PASS" if r["p50"] <= tgt[r["test"]] else "SLOW"}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video"); ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--conc", type=int, default=4); ap.add_argument("--out", default="results.json")
    a = ap.parse_args()
    load_env()
    for k in ("COSMOS3_REASON_URL", "GPU_BEARER_TOKEN"):
        if not os.environ.get(k):
            sys.exit(f"missing {k}")
    with tempfile.TemporaryDirectory() as tmp:
        m = make_media(a.video, tmp)
        print("media bytes:", {k: len(v) for k, v in m.items()})
        model = model_id(os.environ["COSMOS3_REASON_URL"])
        embed_model = os.environ.get("COSMOS_EMBED1_MODEL", "nvidia/cosmos-embed1")
        tests = build_tests(m, model, embed_model)
        for fn in list(tests.values())[:1]:
            timed(fn)  # warm-up
        rows = []
        print(f'{"test":38} {"conc":>4} {"ok/err":>7} {"p50":>6} {"p95":>6} {"max":>6}')
        for conc in (1, a.conc):
            for name, fn in tests.items():
                if conc > 1 and not name.startswith("cosmos IMAGE"):
                    continue  # contention test only on the hot path
                r = run(name, fn, a.n if conc == 1 else a.n * conc, conc)
                rows.append(r)
                print(f'{name:38} {conc:>4} {r["ok"]:>3}/{r["err"]:<3} '
                      f'{r.get("p50", "-"):>6} {r.get("p95", "-"):>6} {r.get("max", "-"):>6}'
                      + (f'  ERR {r["first_err"]}' if "first_err" in r else ""))
    v = verdict(rows)
    print("\n" + "\n".join(v))
    json.dump({"rows": rows, "verdict": v, "ts": time.time()}, open(a.out, "w"), indent=2)
    print("saved", a.out)


if __name__ == "__main__":
    main()
