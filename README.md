# CURRENT

### Changing the future of electronics education.

**CURRENT is a real-time video agent that watches your breadboard, understands what you have built, and teaches you step by step, out loud, before you power anything on wrong.**

It is not a chatbot you have to ask. It is always on, it speaks first, it mirrors your real circuit as a live 3D digital twin, and it remembers every project you have ever built.

> Built for the **VAST Builders Challenge: Real-Time Video Agents**.
> Live demo: open the deployed app (`https://video-lab-team-14.cosmos.vastdata.com/app/`) or the workshop portal → **App**.

---

## Why this matters

Every maker has wired an LED backwards and spent an hour wondering why nothing happens. Electronics is learned by doing, but the feedback loop is broken: a mistake is invisible until something fails, and a teacher can only be at one bench at a time.

CURRENT closes that loop. Point a camera at the bench and it:

1. **Sees** the board, the Arduino Nano or ESP32, the LED, the resistor and the jumper wires.
2. **Understands** what is wrong or missing, and why it matters physically.
3. **Acts** by speaking up, animating the fix in 3D, and walking you to the next step.
4. **Remembers** your project, so you can walk away and resume where you left off.

Learners get a patient tutor. Teachers get a bench they can watch in 30 seconds. Classrooms get a teaching assistant for every table.

---

## Judging criteria, and how CURRENT answers them

| Criterion | What we built |
|---|---|
| **Idea**: a compelling application of the video stack | A real-time video agent for hands-on learning. Footage is understood and *acted on*: corrections, next steps, spoken answers. It teaches the *why*, not just the *what*. |
| **Technical implementation**: quality, reproducible, documented I/O | Clean async Python service, typed message protocol, deterministic circuit verifier, offline unit tests, one-command deploy, documented inputs, outputs and evaluation steps (below). |
| **Design**: thoughtful, intuitive UX | One screen: live camera, a 3D twin of the circuit, the five-step plan, and a coach you can talk to. Calm by design: warnings are small, debounced and dismissible, because vision is sometimes wrong. |
| **Impact**: at least 3 sponsor tools | **VAST Data** (S3, Video Search & Summary), **NVIDIA Cosmos** (Cosmos3-Reason, Cosmos-Embed1) and **Cursor by SpaceXAI** (see [Sponsor tools](#sponsor-tools)). |
| **Presentation**: a 2-minute demo | The demo is the judge: they touch the Arduino, break the circuit, and watch CURRENT catch it. Script in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md). |

---

## What it does

- **Always-on, proactive coaching.** It speaks first: it flags a likely mistake, offers a hint when you go quiet (nudge → hint → exact hole), explains the *why*, and asks "ready for the next step?" instead of racing ahead.
- **A live 3D digital twin.** The circuit the camera sees is rebuilt in 3D with real parts (board, LED colour, resistor bands, wires). When something is off, an animated arrow shows exactly which wire to move. Spin, zoom and view presets are under your control.
- **Step-by-step plan.** All five steps of the build are always visible, with what to do and why. Finished steps stay finished.
- **Talk to it.** Hold the mic and ask "why do I need a resistor?" and get a spoken answer in about a second.
- **Build anything, not just Blink.** Say or type a project ("I want to build a traffic light with three LEDs") and it generates a validated, step-by-step plan for your board.
- **Arduino Nano first, ESP32 supported.** Pin logic, voltage and sketch differ per board.
- **A digital twin that remembers.** Projects, twin snapshots and key frames are stored in VAST. Saved projects are listed from VAST (`/api/projects`) and the service can resume one where you stopped, recalling the slips you made last time.
- **Human override.** Because vision is imperfect, every warning has a one-tap "Looks fine to me" dismiss, and you can move on at any time with the Next button or by saying "next".

---

## How it works

```
 Phone / laptop camera ──frames──┐
 Microphone ──────────speech─────┤
                                 ▼
                    ┌──────────────────────────┐
                    │  CURRENT service (async) │
                    │                          │
  change / scene    │  1. detect: is anything  │
  gate              │     new in the frame?    │
                    │  2. NVIDIA Cosmos3-Reason│──► parts, colours, LED lit
                    │     reads the frame      │
                    │  3. deterministic        │──► rules + circuit simulation
                    │     verifier checks it   │    gate every warning
                    │  4. coach phrases ONE    │──► short spoken guidance
                    │     next action          │
                    │  5. NVIDIA Cosmos-Embed1 │──► "have you made this slip
                    │     mistake memory       │     before?"
                    │  6. VAST stores twin,    │──► projects, snapshots, video
                    │     frames, projects     │
                    └────────────┬─────────────┘
                                 ▼
        3D digital twin · step plan · spoken coach · trace panel
```

Two principles keep it trustworthy:

- **The model describes, the verifier decides.** Vision output is never spoken as fact. A deterministic checker (circuit simulation plus rule detectors) must agree first, and a warning is only raised after two consecutive looks agree.
- **Everything is visible.** The *Behind the scenes* panel shows every call to every service with its latency, so judges can see the stack working.

### Measured on the deployed app

| Step | Typical latency |
|---|---|
| Frame change detection | ~75 ms |
| Cosmos3-Reason: parts and LED state from a frame | 2.7 to 4.5 s |
| Spoken question → transcript | ~0.3 s |
| Question → answer | ~0.6 s |
| Generate a custom 5-step project | ~6 s |

---

## Sponsor tools

### VAST Data
- **VAST S3**: object store for the digital twin's memory. Saves a twin snapshot and a key frame for each confirmed observation, and stores every project (steps, progress, parts seen, mistakes) so it can be listed and resumed.
- **VAST Video Search & Summary (VSS)**: the session video can be sent to the team's VSS instance (Cosmos-powered analysis, search and summary), so a build session becomes searchable video.
- **VAST DataEngine**: the pipeline behind VSS that ingests, segments and indexes uploaded video.

### NVIDIA Cosmos
- **Cosmos3-Reason**: the vision-language model that turns each camera frame into a structured twin: which board, which parts, LED colour and whether it is lit, wires and visible issues.
- **Cosmos-Embed1**: embeddings for mistake memory, so the coach can tell you when you are repeating a slip.

### Cursor by SpaceXAI
- Developed against the Builders Challenge workshop VM using **Cursor Remote-SSH**, together with the VAST Cursor skills for the video stack.

---

## Technologies used

| Layer | Tech |
|---|---|
| Backend | Python 3, `aiohttp` with WebSockets and server-sent events, async throughout |
| Vision and memory | NVIDIA Cosmos3-Reason, NVIDIA Cosmos-Embed1 |
| Storage and video | VAST S3 (`boto3`), VAST Video Search & Summary |
| Verification | Modified nodal analysis circuit solver, rule detectors, Z3 invariant check |
| Frontend | Vanilla JS modules, `three.js` (3D twin, bloom), GSAP, Web Speech API, no build step |
| Deploy | Kubernetes (`deploy.sh`), single pod, assets served with no-cache headers |
| Tests | Python `unittest`, offline, no network needed |

---

## Run it

**Deployed:** open `https://video-lab-team-14.cosmos.vastdata.com/app/` (https is required for the camera), allow the camera, pick **Nano** or **ESP32**, then click a step or say "Blink".

**Deploy your own** (on the workshop VM, which provides the team config and credentials):

```bash
bash deploy.sh
```

**Run locally** (needs the service endpoints as environment variables, see `app/config.py`):

```bash
pip install -r app/requirements.txt
cd app && python main.py          # serves the UI at http://localhost:8080
```

**Run the tests:**

```bash
cd app && python -m unittest discover -p '*test.py'
```

**No hardware? No network?** Open `/?demo=1` for a scripted replay of a full session.

---

## Inputs, outputs and how to evaluate

**Inputs:** camera frames (JPEG, about 1 per second), microphone audio (WAV), typed text, button clicks.

**Outputs:** a structured digital twin, verified findings, spoken guidance, a 3D scene, a step plan, and stored projects.

**Main interfaces**

| Interface | Purpose |
|---|---|
| `GET /` | the app |
| `WS /ws?code=<session>&role=phone\|laptop` | frames, audio and asks in; twin, findings, guidance, coach state and trace events out |
| `GET /api/projects` | saved projects from VAST, newest first |
| `GET /api/sponsors` | live health of every sponsor service |
| `POST /api/verify` | run the deterministic verifier on a twin |
| `POST /api/session/{code}/upload` | send the session video to VAST VSS |
| `GET /health` | service status |

**Evaluate it in two minutes**

1. Open the app, pick **Nano**, start **Blink**. Confirm the five steps show and the 3D twin appears.
2. Place the board, LED and resistor on a breadboard in front of the camera. Watch the twin mirror the parts, with the trace panel showing the model calls and latencies.
3. Sabotage it: flip the LED or pull the resistor. After two agreeing looks, CURRENT speaks a short warning and the 3D arrow shows the fix.
4. Hold the mic and ask "why do I need a resistor?"
5. Say "I want to build a traffic light with three LEDs". A new five-step plan appears, and the project is saved to VAST (`GET /api/projects`).

Pressing `1`–`5` triggers a sample warning for that step and `Shift+1`–`5` a sample "step correct", for rehearsal. `?` shows the key list.

---

## Project layout

```
app/                 async service: perception, coach, verifier, sponsors, projects
  perception/        frame handling and Cosmos3-Reason client
  verifier/          circuit solver, rule detectors, invariant check
  sponsors/          VAST S3 / VSS and Cosmos-Embed1 integrations
frontend/            UI, 3D digital twin, trace panel, replay mode
docs/DEMO_SCRIPT.md  the 2-minute judge demo
deploy.sh            one-command Kubernetes deploy
```

---

## Honest limits

- Cosmos3-Reason reliably identifies the parts and whether the LED is lit. The exact wiring it traces can vary between frames, which is why warnings need two agreeing looks and can be dismissed with one tap.
- Tested with the Arduino Nano. ESP32 support is in the plan and pin logic but has not been run on a physical ESP32.
- Sending the session video to VAST VSS works on the backend; indexing time depends on the cluster.

---

## Team

Built by the CURRENT team at the VAST Builders Challenge.
