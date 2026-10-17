# CURRENT — live backend

Camera stills from the browser → **Cosmos3 reasoner** for board state.  
Indexed Arduino clips in **VAST** are few-shot examples for better placement advice (not the live video source).

## Run

Env already on the VM (`INGRESS_URL`, `USERNAME`, `PASSWORD`, `GPU_BEARER_TOKEN`, `WANDB_API_KEY`).

```bash
cd backend
pip install -r requirements.txt
PORT=8080 python main.py
```

Open `http://localhost:8080` — Arm camera → frames post to `/api/frame` every few seconds.

## API

| Route | Purpose |
|-------|---------|
| `GET /api/session` | steps + last caption |
| `POST /api/frame` | `{ image_jpeg_b64 }` → Cosmos + step/alerts |
| `POST /api/chat` | question using live vision + VAST examples |
