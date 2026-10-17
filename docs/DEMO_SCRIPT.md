# CURRENT: judging pitch and 2-minute live demo

Round 1 = 2 min at the table. Top 5 = 3 min on stage. Demos beat slides: the judge's hands go on the Arduino within 20 seconds.

## One-line pitch
"CURRENT is a teacher that watches your breadboard, speaks up before you power it on wrong, and remembers you. Don't take my word for it: break it."

## Pitch points (map to criteria)
- **Idea:** Not a chatbot you ask. Always-on and proactive: it teaches step by step, interrupts on mistakes, and asks "Ready for the next step? Say next" instead of racing ahead. Every spoken warning is gated by a deterministic verifier (11 named mistake detectors in `app/mistakes.py`); the LLM only phrases verified facts.
- **Technical:** Camera -> YOLO11 gate (~75 ms) -> Cosmos3-Reason (2.7-4.5 s) -> verifier -> W&B Llama coach. Voice: Canary ASR ~0.3 s, coach reply ~0.6 s. The coach speaks a mistake only after two consecutive agreeing analyses, so there are no flickery false alarms.
- **Design:** 3D digital twin mirrors the real parts live, animates the fix (arrow moving the wire), spin toolbar. Right-hand "Trace" trace shows every sponsor call with its latency. Hidden step menu lets a human override the AI.
- **Impact (sponsor tools, 7 visible):** NVIDIA Cosmos3-Reason, YOLO11, Canary-1B, Cosmos-Embed1 (all on CoreWeave GPUs), W&B Inference, VAST S3 (+ VSS search). Projects and twin state persist in VAST, so it resumes: "Welcome back, we were on step 4... you had the LED backwards last time."
- **Presentation:** The judge is the demo. They sabotage a real board.

## Pre-demo checklist (10 min before)
- [ ] Open https://workshop.thecosmoslabs.com -> **App**. Tab 2: same site at `/?demo=1` (offline replay fallback).
- [ ] Phone/laptop camera on a stand, looking down at the Nano + breadboard. Steady, whole board and LED in frame, no tilt.
- [ ] Your hands are OUT of frame at start. Judge hands will enter: that is the point.
- [ ] Lighting: bright, no glare on the breadboard, no shadow from your head.
- [ ] Browser mic permission granted; test one hold-to-talk question. Voice/TTS unmuted, laptop volume up, table noise check.
- [ ] Pick **Nano**, start **Blink** (or let the project card load). Run one full cycle: LED flipped -> warning -> fixed. Then restore the correct circuit and restart the step.
- [ ] Confirm sponsor chips are green and trace shows cosmos/yolo/canary lines.
- [ ] Have a pre-built Traffic light project saved in Memory (Resume card) for the wow-2 beat.
- [ ] Spare LED, resistor and jumper on the table.

## 2-minute demo (table)
| Time | Presenter says (exact) | Judge does | Screen shows | Sponsor firing (point to it) |
|---|---|---|---|---|
| 0:00-0:10 | "This is CURRENT. A real Arduino Nano, a camera, and a teacher that never looks away. Watch the right side." | Nothing yet | Live camera, YOLO boxes, 3D twin building the Nano, LED, resistor | **YOLO11 ~75 ms**, **Cosmos3-Reason** spans in trace (CoreWeave chip) |
| 0:10-0:25 | "It sees the board, LED colour, resistor. That 3D twin is built from the camera, not from a script. Judge, hand me nothing: you break it. Pull the LED out and plug it in **backwards**." | Flips the LED (long leg to GND side) | Twin LED flips; trace shows cosmos pass | **Cosmos3-Reason** parts + led_lit |
| 0:25-0:40 | "Notice it waits for two matching looks, so no false alarms. Three... two..." | Hands out of frame, holds still | Pipeline lights Frame -> YOLO -> Cosmos -> Coach; red finding "LED is backwards" | Verifier (local), then **W&B Inference** coach span |
| 0:40-0:55 | (silent, let it speak) | Listens | Voice: "Stop. Your LED is backwards... long leg faces the resistor side." Twin animates the fix arrow | **W&B Inference** phrasing; browser TTS. **WOW 1** |
| 0:55-1:10 | "Now the judge fixes it, guided by the arrow." | Flips LED back | Finding clears, "Nice catch", then "Ready for the next step? Say next." | Cosmos re-check, **Cosmos-Embed1** span ("embed") |
| 1:10-1:25 | "Now sabotage harder: pull the resistor out." | Removes the resistor | After two agreeing looks: "No series resistor... LED can burn out" | Cosmos + verifier + coach. **WOW 2**: second gross fault caught |
| 1:25-1:40 | "Don't type. Hold to talk: ask it anything." Judge asks: "Why do I need a resistor?" | Holds talk button, asks | Transcript appears ~0.3 s, answer starts ~0.6 s later, spoken | **Canary-1B** ASR then **W&B Llama** coach. **WOW 3**: instant voice |
| 1:40-1:52 | "It also remembers. This is VAST: projects and twin snapshots saved. Last time you reversed the LED, so it warns you faster." Open **Memory** tab, show Resume card | Optionally say "a traffic light with three LEDs" | New 5-step project in ~6 s; Memory lists saved projects, "Welcome back, step 4..." | **VAST S3** span, **Cosmos-Embed1** mistake recall |
| 1:52-2:00 | "Seven sponsor tools, one real board, zero scripts. Detect, verify, speak, remember. That is CURRENT." | - | Trace panel full of sponsor spans | All chips |

If the judge only wants one sabotage, drop the 1:10-1:25 beat and expand the voice question.

## Three wow moments
1. **Judge flips the LED and CURRENT interrupts out loud** before anything is powered.
2. **Resistor pulled, second caught** with the 3D arrow moving the wire back.
3. **Voice question answered in under a second** (Canary 0.3 s + coach 0.6 s), then "Welcome back... you had the LED backwards last time" from VAST memory.

## If it goes wrong
| Problem | Fix |
|---|---|
| Camera not detecting parts | Ask the judge to hold the board steady, check lighting; step **⋯ menu -> "Re-check the board now"** |
| False or stale warning | Step **⋯ menu -> "System is wrong: dismiss warning"**; say "the human can always override the AI" |
| Fault not flagged after ~8 s | Subtle faults are not reliable. Say "needs two agreeing looks", make it grosser (LED fully reversed, resistor fully out) |
| Voice not transcribed | Check mic permission, hold button the full sentence, or type the question |
| TTS silent | Unmute tab/volume; read the on-screen guidance aloud |
| Network or backend down | Switch to tab 2 `/?demo=1`: scripted Blink replay (backwards LED -> fix -> resistor -> GND -> done). Say: "This is the recorded session replay; the live one is the same pipeline." Be honest it is a replay |

## 30-second on-stage version (top 5)
0:00 "Every maker has wired an LED backwards. CURRENT watches the breadboard and stops you first." (point camera at Nano)
0:07 Judge or you flips the LED. 0:12 CURRENT speaks the warning; twin arrow shows the fix.
0:20 "Cosmos reads the frame, YOLO gates it, a deterministic verifier checks it, W&B phrases it, Canary hears you, VAST remembers you."
0:27 "Don't ask it. Break it. Table 3." Done.

## Judge Q&A
1. **Why not Gemini Live?** Live answers when asked and trusts its own eyes. CURRENT is always-on and proactive, every warning passes a deterministic verifier (so it does not hallucinate a fault), and the 3D digital twin persists in VAST so it remembers your projects and past mistakes.
2. **Why this stack?** Each tool does the job it is best at: YOLO as a cheap change gate, Cosmos3-Reason for scene understanding, Canary for fast ASR, Embed1 for mistake memory, W&B Llama for fast phrasing, VAST for durable state. Plain aiohttp + three.js, no build step, under 1 MiB.
3. **What is real vs simulated?** Real: the camera, Nano, all model calls on CoreWeave GPUs, VAST S3 writes. Simulated: only `/?demo=1`, a scripted replay used as a fallback, labelled as such.
4. **Latency?** YOLO ~75 ms, Cosmos 2.7-4.5 s per frame, Canary ~0.3 s, coach ~0.6 s, project generation ~6 s. A warning needs two agreeing frames, so ~6-9 s from fault to voice, by design.
5. **How are sponsor tools used?** All are visible as spans in the right-hand trace: Cosmos3-Reason (perception), YOLO11 (gate), Canary (voice), Embed1 (mistake recall), CoreWeave (hosting), W&B Inference (coach), VAST S3/VSS (projects, frames, resume). `GET /api/sponsors` shows live status.
6. **Is it reliable at tracing wires?** Parts, LED colour and lit state are reliable. Wiring between frames is noisier, which is why we use a two-agreement rule and a human override menu. We demo gross faults.
7. **Does it write the Arduino code?** Not in this deployment; the curriculum tells you to upload Blink. Code generation is on a separate branch, not deployed.
8. **What's next?** Verified ESP32 on real hardware, one-tap session upload into VSS for search across builds, code generation, a calibrated hole detector, and phone layout.

## Do not promise
- ESP32 working on a real board (not verified live).
- "Send session to VAST VSS" button / appearing in VSS explore (backend upload worked, search unconfirmed, button untested).
- Arduino code generation / MCP (branch `wow-code`, not deployed).
- Phone-width layout.
- Subtle faults (wrong hole, off-by-one row) or exact wire tracing between frames.
- Auto-advance: it asks "say next".

## Proof points for the submission page
1. YOLO11 gate ~75 ms per frame.
2. Cosmos3-Reason 2.7-4.5 s per frame on CoreWeave, returning Nano, resistor, LED colour, wires, led_lit.
3. Voice round trip ~0.9 s: Canary ~0.3 s + W&B Llama coach ~0.6 s.
4. Free-form "a traffic light with three LEDs" -> 5-step project in ~6 s.
5. 7 sponsor tools in one trace (Cosmos3-Reason, YOLO11, Canary, Embed1, CoreWeave, W&B, VAST) and 11 deterministic mistake detectors.
