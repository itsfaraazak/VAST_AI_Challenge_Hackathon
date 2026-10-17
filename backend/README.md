# CURRENT — backend

Replay indexed Arduino bench clips and advise with a Wokwi connectivity world-model.

## Run locally

```bash
cd backend
pip install -r requirements.txt
PORT=8080 python main.py
```

Needs `INGRESS_URL` / `USERNAME` / `PASSWORD` (or `VSS_*`) and optionally `WANDB_API_KEY` from the challenge VM.

Open `http://127.0.0.1:8080`. Workshop deploy: https://workshop.thecosmoslabs.com → **App**.

## Simulator

- `GET /api/sim` — Blink `diagram.json` + `sketch.ino` + advice
- `POST /api/sim/sync` — rebuild from the session circuit note
- `POST /api/sim/advise` — connectivity check (resistor / D13 / GND)
- `POST /api/sim/apply` — apply a `next_actions[].id`

The UI panel embeds Wokwi (`experimental/embed`). ElectronicAI on `Design_verification` uses the same `simulator.py` as a `simulate_circuit` agent tool.
