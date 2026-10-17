# CURRENT — how perception actually works

## Why your jacket was “calling Cosmos”

Yes — we **were** hitting the GPU. That was the bug, not a fake HUD.

1. The UI sends a JPEG ~1 Hz over the WebSocket.
2. The worker always tried **YOLO** then **Cosmos**.
3. YOLO was called with `image_base64`, but the hackathon NIM only accepts `url` **or** `video_base64`. Every YOLO call **422’d**, so we fell back to a **perceptual hash**.
4. A moving person changes that hash every frame → treated as “scene changed”.
5. Even without change, a **5s heartbeat** re-fired Cosmos.
6. So Cosmos ran on your North Face jacket. The HUD `COSMOS calling… / yolo — ms` meant Cosmos was in flight; YOLO had failed (no useful ms/labels).

That is **reactive**, but it was reacting to **pixels**, not to **breadboards**.

## Correct call path (now)

```
Camera JPEG
    │
    ▼
YOLO11  POST $YOLO_URL/v1/infer
        body: { video_base64: <jpeg>, filename: "frame.jpg", include_frames: true }
        Auth: Bearer $GPU_BEARER_TOKEN
        → labels + xyxy boxes (COCO). Note: COCO has no “breadboard” class.
    │
    ▼
GATE (local)
        reject person/animal-dominant / irrelevant COCO (e.g. “cat” on a jacket)
        allow empty COCO (close-up board often has no COCO objects)
        broadcast perception_skip when blocked  →  Cosmos NOT called
    │
    ▼ (only if allow or Force Cosmos)
Cosmos3-Reason  POST $COSMOS3_REASON_URL/v1/chat/completions
        content: [ text prompt, image_url data:image/jpeg;base64,... ]
        → twin JSON: scene, observation, components, nets, placements (hole letters), wiring_check
    │
    ▼
Coach (W&B) phrases what was seen + one next wire action
Canary-1B for hold-to-talk ASR (separate path)
```

## UI proof you can see

- Pipeline strip: **Frame → YOLO → Gate → Cosmos → Coach** lights the active stage.
- **YOLO boxes** toggle draws COCO bboxes on the video.
- **Verbose HUD** shows gate reason + `called_cosmos: true|false`.
- **Force Cosmos** bypasses the gate once (debug / demo).
- Twin panel shows `observation`, `placements` (e.g. `E12`), `wiring_check`.

## Hole / row checking

Cosmos is asked for breadboard hole letters (`A12`, `E15`, …) in `placements` and whether they match Blink (`D13 → 220Ω → LED anode; cathode → GND`). That is **VLM judgment**, not a calibrated hole detector — good for coaching, not metrology. YOLO cannot do hole IDs (COCO only).

## Skills

Builders Challenge skills are copied into this repo at `.cursor/skills/` (from `vast-builders-challenge/.cursor/skills/`).
