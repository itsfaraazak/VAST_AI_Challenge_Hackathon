# CURRENT — frontend

Bench-partner UI for the VAST hack: live video, guided build sequence, chat + voice.

## Run

No build step. From this folder:

```bash
python3 -m http.server 5173
```

Open `http://localhost:5173`. Camera needs a secure context (localhost is fine).

## Layout

- Top stage: **3 : 1** — video | steps
- Bottom: chat thread + hold-to-talk mic
