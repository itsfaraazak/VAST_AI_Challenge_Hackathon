# Bench Buddy backend

Replays already-indexed Arduino bench clips through the CURRENT UI. Search and captions stay on the team video index. Chat is phrased from agent Q&A evidence and W&B inference.

## Run locally

`INGRESS_URL`, `USERNAME`, `PASSWORD`, and `WANDB_API_KEY` must already be in the environment. The process listens on `0.0.0.0:$PORT` (default 8080).

```bash
cd backend
pip install -r requirements.txt
PORT=8080 python main.py
```

## Deployed app

Open https://workshop.thecosmoslabs.com and click App.
