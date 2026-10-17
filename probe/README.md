# Latency probe

Tests whether a 2-4 s live perception loop is feasible against the shared GPU endpoints.

Run **on the workshop VM** (Cursor over SSH). `/config` and the GPU env vars do not exist elsewhere.

```bash
git fetch && git checkout latency-probe
python3 probe/latency_probe.py -n 5 --conc 4 --out probe/results.json
# better: use real footage of a breadboard, cut to clips/frames with ffmpeg
python3 probe/latency_probe.py --video my_breadboard.mp4
```

Never paste `probe/results.json` with secrets: it contains none, only timings and error text.

## What it measures

| Test | Why |
|---|---|
| cosmos text-only | network + queue baseline |
| cosmos IMAGE short / twin-json | **does `image_url` work?** and the fast-path frame latency |
| cosmos CLIP 2s / 4s | fallback path if images are rejected |
| cosmos time-to-first-token | what the user feels if we stream |
| yolo CLIP2s, embed1, canary 3 s | other legs of the loop |
| conc>1 on the IMAGE tests | contention from other teams on the shared GPU |

## Decision rule

- IMAGE short p50 <= 3 s and twin-json p50 <= 6 s at conc=1: real-time loop is go.
- IMAGE rejected (HTTP 4xx): use CLIP2s path; budget the loop accordingly.
- conc=4 p95 more than 2x conc=1 p50: contention is the risk. Serialize calls, one in flight per session.
- Cosmos too slow: YOLO change-detection as the fast trigger, Cosmos only on change.
