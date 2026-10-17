# ElectronicAI — AI Electronics Technician

An AI assistant that helps people understand, diagnose, and repair electronics,
built **on the VAST Builders Challenge video stack**. It pairs the challenge's
real video search / Q&A infrastructure with a safety-gated, evidence-based
diagnostic reasoning agent.

Narrow first use case: **visual troubleshooting of circuit boards and components**
(PCBs, resistors, capacitors, diodes, transistors, ICs, connectors). The
architecture is specialty-pluggable — devices, embedded, test gear, industrial,
and education can be added behind the same agent + evidence model.

---

## What this is (and an honest limitation up front)

The challenge's indexed corpus is **traffic / driving / warehouse footage**
(I-24 highway, Toronto/SF dashcam, neighborhood cams) — there is **no
electronics-repair video** in it. This app does **not** pretend otherwise:

- **Video search, evidence retrieval, and Q&A run for real** against your team's
  index — ranked clips, timestamps, scores, model descriptions, playback.
- **Electronics diagnosis runs on the LLM** (general knowledge) and is clearly
  separated in the UI from **observed video evidence** and from **the user's own
  reported readings**. The agent is instructed never to claim it measured or saw
  something it didn't.
- If authorized electronics footage is later ingested through the normal
  pipeline, it becomes searchable with zero code change — the retrieval path is
  identical.

No integration is faked. When a backend isn't configured/reachable, the app
returns an explicit **interface boundary** (HTTP 503/502 with a message), never a
fabricated clip or answer.

---

## What I built

- `main.py` — a Flask server (deps: `flask`, `requests` only) with:
  - **`VSSClient`** — server-side auth to the VSS retrieval backend (JWT, cached,
    re-login on 401) and typed calls to the real endpoints.
  - **`LLMClient`** — W&B serverless inference over the OpenAI-compatible
    `/chat/completions` endpoint, scoped to your W&B project.
  - **Diagnostic agent** (`run_agent`) — a safety-first electronics-technician
    system prompt + a `search_video` tool. The model decides when to search; the
    server executes the search against real VSS and feeds results back for a
    grounded answer. Output ends with a structured `SUSPECTED FAULT / SUPPORTING
    EVIDENCE / UNCERTAINTY / NEXT SAFE TEST` block the UI renders into the
    Diagnosis panel.
  - **Honest status** (`/api/status`) and labelled boundaries everywhere.
- `templates/index.html` — a dark, self-contained (no CDNs) **diagnostic
  workstation** UI: left sidebar (New Diagnosis / Projects / Video Library /
  Docs + specialties), conversational panel with example prompts and
  loading/empty/error states, a **Video Evidence** panel (clips with timestamps,
  scores, descriptions, click-to-play), a **Diagnosis** panel, and a **Component
  Reference** panel. A top banner surfaces any disconnected backend.
- `k8s/` — `deploy.sh` + `manifests.yaml` implementing the
  `deploy-app-no-registry` skill (public image, code via ConfigMap, creds via
  Secret, Ingress at `/app`).

## How the video agent works

```
user question
   │
   ▼
W&B LLM (system prompt: safety + evidence + diagnostic workflow, tool: search_video)
   │  model chooses to search?
   ├── no ──────────────► grounded educational / diagnostic answer
   └── yes ─► VSSClient.search() ─► POST $VSS_URL/api/v1/search
                 │                     (real ranked clips: timestamps, scores, descriptions)
                 ▼
          tool results fed back to the LLM ─► grounded answer + Evidence panel cards
```

The agent is told the archive is traffic/warehouse footage and must report
honestly when a search doesn't contain electronics — so it won't dress up a
dashcam clip as a circuit-board demo.

## Which existing services and APIs I reused

| Reused | Endpoint / skill |
|---|---|
| Auth | `POST /api/v1/auth/login` (`retrieval/login`) |
| Search | `POST /api/v1/search` (`retrieval/search`) |
| Grounded Q&A | `POST /api/v1/agent/search-and-answer` (`retrieval/agent-qa`) — available via `VSSClient.search_and_answer` |
| Browse | `GET /api/v1/videos/explore` (`retrieval/videos`) |
| Playback | `GET /api/v1/videos/stream?...&token=` (`retrieval/videos`) |
| App reasoning | W&B serverless inference (`WANDB_*`, OpenAI-compatible) |
| Deploy | `deploy-app-no-registry` skill (ConfigMap + Secret + Ingress `/app`) |

Credentials are read from the environment the VM already provides
(`INGRESS_URL/USERNAME/PASSWORD` or the `VSS_*` Secret, and `WANDB_*`). No secret
is ever sent to the browser. No services are rebuilt.

## What works / what's incomplete

**Works (verified locally):** server boots; UI renders; `/health` and
`/api/status` report real capability; chat and search return honest interface
boundaries when backends are unset; a configured-but-unreachable backend degrades
to a labelled 502 instead of crashing; the K8s manifests follow the deploy skill.

**Requires the VM to exercise end-to-end** (not reachable from off-VM): live VSS
search results and live W&B answers. The code calls the real APIs documented in
the skills; it just needs the env vars that exist on the VM.

**Intentionally scoped out of the MVP:** YOLO detection overlays
(`/videos/detections`), whole-video `synthesize` reports, re-ingest with an
electronics prompt, and persisted projects. All are reachable with the existing
`VSSClient` and left as clearly-marked extensions.

---

## Run locally

```bash
cd electronicai
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in if you have VSS/W&B access; optional
set -a; [ -f .env ] && . .env; set +a
python main.py                  # http://localhost:8080
```

Without credentials the app runs and shows honest "not connected" boundaries.
With `VSS_*` and `WANDB_*` set, chat, search, and playback work live.

## Deploy on the challenge cluster (from the VM)

```bash
bash k8s/deploy.sh
# then open https://workshop.thecosmoslabs.com and click the App button
```

---

## Demo script (≈3 min, for a live builders-challenge presentation)

1. **Frame it (15s).** "ElectronicAI is an AI electronics technician. It reasons
   about faults *and* grounds answers in real indexed video — and it's honest
   about what the video does and doesn't show."
2. **Show honesty (15s).** Point at the status chips + corpus note: "Today's
   index is traffic/warehouse footage, so I'll demo the real video agent on that
   corpus and the diagnostic reasoning separately — no faking."
3. **Real video search (45s).** Ask: *"Find the moment a vehicle brakes hard at
   an intersection."* Show ranked clips in the Evidence panel — timestamps,
   scores, model descriptions — and click one to play. This is the live VSS API.
4. **Evidence discipline (30s).** Ask: *"Does this clip show a circuit-board
   fault?"* The agent answers honestly that the footage is traffic, not
   electronics — demonstrating it won't invent a diagnosis from unrelated video.
5. **Diagnostic reasoning + safety (45s).** Ask: *"My board won't power on. What
   are the likely faults and what should I test first?"* Watch the Diagnosis
   panel fill with ranked hypotheses and a **safe** next test, with the safety
   warning about discharging capacitors before probing.
6. **Follow-up (20s).** *"I measured 0V on the 3.3V rail — what now?"* The agent
   revises its hypothesis from the reported reading. Close on the separation of
   observed evidence vs. model knowledge vs. user readings.

**Success criterion met:** a judge asks a question, sees real retrieved video
evidence with timestamps, and gets a useful, transparent answer with explicit
uncertainty — no fake integrations or unsupported claims.
