/** /?demo=1 — scripted Blink session pushed through the real handlers (no backend). */
const app = window.CurrentApp;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let run = 0, board = "nano", stage = 0, bad = false, tid = 100;

const STEPS = [
  { id: "orient", title: "Orient the board", why: "Pins sit on both long edges; knowing which way is up keeps D13 and GND from getting swapped.", action: "Seat the board across the center channel.", pins: ["D13", "GND"] },
  { id: "led", title: "Seat the LED", why: "LEDs only conduct one way. Long leg = anode (+).", action: "Place the LED, long leg toward the resistor side.", pins: ["D13"] },
  { id: "resistor", title: "Add 220Ω resistor", why: "Without it the LED draws too much current: (5V−1.8V)/15mA ≈ 220Ω.", action: "Resistor from D13 row to LED anode row.", pins: ["D13"] },
  { id: "gnd", title: "Close the circuit to GND", why: "Current needs a return path to complete the loop.", action: "Jumper LED cathode row to GND.", pins: ["GND"] },
  { id: "flash", title: "Run Blink", why: "Pin 13 toggles HIGH/LOW every second.", action: "Upload File > Examples > Basics > Blink.", pins: ["D13"] },
];
const PROJECT = { id: "blink", title: "Blink — external LED", pitch: "Blink an LED safely." };
const coachState = (i, extra = {}) => ({
  phase: "teaching", project_id: "blink", project: PROJECT, board, step_index: i, step_total: STEPS.length,
  step: STEPS[i], steps: STEPS, mistakes: [], projects: [], ...extra,
});
const MISTAKE = { id: "led_reversed", title: "LED is backwards", severity: "error", parts: ["led"], pins: ["D13", "GND"], fix: "Flip the LED: long leg toward the resistor" };

const say = (text, source = "llm", ms = 640) => app.onBackend({ type: "guidance", text, source, ms });
let sid = 0;
async function span(stage_, label, model, sponsor, ms, detail = "") {
  const id = ++tid + sid++;
  app.onBackend({ type: "trace", id, stage: stage_, label, model, sponsor, status: "start", t: Date.now() / 1000 });
  await sleep(Math.min(ms, 700));
  app.onBackend({ type: "trace", id, stage: stage_, label, model, sponsor, status: "ok", ms, detail, t: Date.now() / 1000 });
}
function yolo(extra = []) {
  const boxes = [{ label: "breadboard", confidence: 0.94, xyxy: [60, 120, 600, 340] }, { label: board === "nano" ? "arduino_nano" : "esp32", confidence: 0.91, xyxy: [90, 130, 330, 215] }];
  if (stage >= 1) boxes.push({ label: "led", confidence: 0.88, xyxy: [400, 235, 440, 290], bad });
  if (stage >= 2) boxes.push({ label: "resistor", confidence: 0.85, xyxy: [330, 200, 400, 240] });
  boxes.push(...extra);
  app.onBackend({ type: "yolo", ok: true, ms: 18 + Math.random() * 6, shape: [360, 640], boxes, labels: boxes.map((b) => b.label), gate: { allow_cosmos: true, reason: "board+parts", confidence: 0.9 } });
}
async function perceive(note) {
  yolo();
  await span("yolo", "YOLO detect", "yolov8", "local", 21);
  app.onBackend({ type: "cosmos_status", state: "calling", yolo_ms: 21 });
  await span("cosmos", "Cosmos twin", "cosmos3-reason", "nvidia", 1180, note);
  app.onBackend({ type: "cosmos_status", state: "done", ms: 1180, scene: "bench" });
  app.onBackend({ type: "twin", twin: { scene: "bench", confidence: bad ? 0.82 : 0.93, observation: note, components: [{ id: "mcu", type: board }, ...(stage >= 1 ? [{ id: "led1", type: "led" }] : []), ...(stage >= 2 ? [{ id: "r1", type: "resistor" }] : [])] }, findings: bad ? [MISTAKE] : [] });
  await span("verify", "Verifier rules", "rules", "local", 4, bad ? "led_reversed" : "ok");
}
async function coachTurn(text, i) {
  await span("coach", "Coach LLM", "wandb-inference", "wandb", 410, text.slice(0, 80));
  app.onBackend({ type: "coach", ...coachState(i, { mistakes: bad ? [MISTAKE] : [] }) });
  say(text);
  span("memory", "Session memory write", "vast-db", "vast", 9);
}

async function script(my) {
  const alive = () => my === run;
  stage = 0; bad = false;
  app.setBoardUi(board);
  app.onBackend({ type: "joined", code: "DEMO42", role: "laptop", coach: { phase: "ask_project", step_index: 0, step_total: 0, projects: [{ id: "blink", title: "Blink — external LED", pitch: "" }] } });
  say("Hi! I'm watching your bench. What do you want to build today?", "curriculum");
  await sleep(3500); if (!alive()) return;
  const name = board === "nano" ? "Nano" : "ESP32";
  app.onBackend({ type: "transcript", text: "Let's do Blink", asr: "canary", ms: 190 });
  await span("asr", "Canary ASR", "canary-1b", "nvidia", 190, "Let's do Blink");
  await coachTurn(`Blink on the ${name} it is. First, seat the board across the center channel so every pin has its own row.`, 0);
  await sleep(1500); await perceive(`${name} on breadboard, no other parts`); if (!alive()) return;
  await sleep(4500); if (!alive()) return;

  stage = 1; bad = true;                                     // LED placed backwards
  await perceive("LED inserted, long leg toward GND row"); if (!alive()) return;
  app.onBackend({ type: "coach", ...coachState(1, { mistakes: [MISTAKE] }) });
  say("Stop. Your LED is backwards. The long leg is the anode and must face the resistor side. Flip it around.", "verifier");
  await sleep(7500); if (!alive()) return;

  bad = false;                                               // child fixes it
  await perceive("LED corrected, anode toward D13 row"); if (!alive()) return;
  app.onBackend({ type: "coach", ...coachState(1, { mistakes: [] }) });
  say("That's it. Polarity is correct now. Nice catch.", "verifier");
  await sleep(4200); if (!alive()) return;

  stage = 2; await coachTurn("Next, a 220 ohm resistor from D13 to the LED anode row. It limits current so the LED does not burn out.", 2);
  await sleep(2500); await perceive("220 ohm resistor linking D13 row to LED anode"); if (!alive()) return;
  await sleep(4000);
  stage = 3; await coachTurn("Last wire: jumper the LED cathode row to any GND pin to close the loop.", 3);
  await sleep(2500); await perceive("Jumper from LED cathode row to GND"); if (!alive()) return;
  await sleep(3500);
  stage = 4; await coachTurn("Circuit complete. Upload the Blink example and watch pin 13 pulse.", 4);
  app.onBackend({ type: "coach", ...coachState(4, { done: true }) });
  await sleep(6000); if (alive()) { stage = 0; script(my); }  // loop for booth demos
}

function start(b) { board = b || board; run++; script(run); }
window.CurrentReplay = {
  restart: start,
  onClient(m) {
    if (m.type === "coach_start") { board = m.board || board; start(board); }
    if (m.type === "ask" && m.text !== "next") { app.onBackend({ type: "transcript", text: m.text, asr: "canary", ms: 200 }); setTimeout(() => say("The resistor limits current to about 15 milliamps, so the LED and the pin both survive."), 900); }
  },
};

/* synthetic bench feed so the left panel looks alive without a camera */
const cv = document.getElementById("demoFeed"), g = cv.getContext("2d");
function drawFeed(t) {
  g.fillStyle = "#0b1218"; g.fillRect(0, 0, 640, 360);
  g.fillStyle = "#d9d4c4"; g.fillRect(60, 120, 540, 220);                  // breadboard
  g.fillStyle = "#555"; for (let x = 70; x < 590; x += 12) for (const y of [135, 150, 165, 250, 265, 280, 295, 310]) g.fillRect(x, y, 5, 5);
  g.fillStyle = "#1a5fa8"; g.fillRect(90, 130, 240, 85);                    // board
  g.fillStyle = "#c0c0c0"; g.fillRect(84, 160, 12, 25);
  if (stage >= 1) { g.fillStyle = bad ? "#ff4040" : "#ff2020"; g.beginPath(); g.arc(420, 258, 14, 0, 7); g.fill(); g.fillStyle = "#ccc"; g.fillRect(414, 270, 3, 20); g.fillRect(424, 270, 3, bad ? 14 : 20); }
  if (stage >= 2) { g.fillStyle = "#c9a36a"; g.fillRect(335, 215, 60, 12); g.fillStyle = "#b22"; g.fillRect(350, 215, 4, 12); }
  if (stage >= 3) { g.strokeStyle = "#3c3"; g.lineWidth = 4; g.beginPath(); g.moveTo(426, 285); g.lineTo(470, 300); g.lineTo(470, 215); g.lineTo(330, 215); g.stroke(); }
  if (stage >= 4) { g.fillStyle = `rgba(255,60,60,${0.2 + 0.2 * Math.sin(t / 250)})`; g.beginPath(); g.arc(420, 258, 40, 0, 7); g.fill(); }
  if (lastBoxes) window.CurrentApp.drawYoloLoop?.();
}
let lastBoxes = false;
(function loop(t) { drawFeed(t || 0); requestAnimationFrame(loop); })();
start("nano");
