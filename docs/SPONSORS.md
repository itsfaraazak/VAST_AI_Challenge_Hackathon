# Sponsor tool usage

| Tool | Role | Where | Visible proof |
|---|---|---|---|
| NVIDIA Cosmos3-Reason (on CoreWeave) | VLM: frame to twin JSON | `app/perception/cosmos.py` | trace span "cosmos", twin panel |
| NVIDIA YOLO11 | change gate | `app/perception/yolo.py` | pipeline strip, boxes toggle |
| NVIDIA Canary-1B | ASR for hold-to-talk | `app/audio/canary.py` | transcript |
| NVIDIA Cosmos-Embed1 | 256-d embeddings of diagnosed mistakes; cosine recall (threshold 0.82) per session | `app/sponsors/embed_memory.py` (`remember`, `recall`) | trace span "embed" |
| CoreWeave | GPU hosting for all NVIDIA models | `app/config.py` | `/api/sponsors` |
| W&B Inference | phrases verified tips only | `app/coach.py` | trace span |
| VAST S3 | `current-live/<session>/` twin JSON, throttled key-frame JPEGs (<=1 per 5 s), summary | `app/sponsors/vast_store.py` | trace span "vast", bucket listing |
| VAST VSS / DB | semantic search of past builds | `app/history.py` | history answer |
| Cursor | coding agent used to build the app and use the provided skills | repo | n/a |

Not implemented: VAST DB row writes and W&B Weave tracing.

## Configuration (env only, never committed)

`S3_ENDPOINT`, `ACCESS_KEY`, `SECRET_KEY`, `S3_CHUNKS_BUCKET`, `VDB_ENDPOINT`, `VASTDB_BUCKET`, `VDB_SCHEMA`, `COSMOS_EMBED1_URL`, `WANDB_*`, `GPU_BEARER_TOKEN`. `deploy.sh` forwards them into the pod Secret from the VM environment (or `/config/*.config`) without echoing values. Every integration fails soft and reports status.

## Tests

`cd app && python -m unittest sponsors.test_sponsors` (mocked S3, registry, embed recall).
