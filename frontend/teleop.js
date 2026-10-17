/* Demo teleop: keyboard shortcuts that inject a believable error / success for a step, in case the live demo goes haywire.
 *   1..5            step N PASSES: show "step N looks right" and move to the next step
 *   Shift + 1..5    step N FAILS: show a possible issue for step N
 *   0 or Esc        clear the note
 *   ?               cheat sheet
 * It only feeds the normal UI handlers (window.__current.onBackend); no backend, no state of its own. */
const STEPS = [
  { title: "Orient the board", action: "Seat the Nano across the centre channel so each pin has its own row.", why: "Pins on opposite sides must not share a strip.",
    err: ["Board may not be seated across the centre channel", "Press the Nano down so its two pin rows straddle the centre gap."], ok: "Nice, the board is seated correctly." },
  { title: "Seat the LED", action: "Place the LED, long leg toward the resistor side.", why: "LEDs only conduct one way. Long leg is the anode (+).",
    err: ["LED may be backwards", "Flip the LED: long leg toward the resistor side, short leg toward GND."], ok: "Good, the LED is the right way round." },
  { title: "Add 220Ω resistor", action: "Resistor from the D13 row to the LED anode row.", why: "It limits current so the LED does not burn out.",
    err: ["Resistor may be missing or on 5V", "Move the resistor's free end to the LED anode row, fed from D13 (not 5V)."], ok: "Resistor in the right place, current is limited." },
  { title: "Close the circuit to GND", action: "Jumper the LED cathode row to a GND pin.", why: "Current needs a return path.",
    err: ["LED cathode may not reach GND", "Add a jumper from the LED cathode row to any GND pin."], ok: "Circuit closed to GND." },
  { title: "Run Blink", action: "Upload File > Examples > Basics > Blink.", why: "Pin 13 toggles once a second.",
    err: ["LED is not blinking yet", "Check the board selection is Arduino Nano, then upload Blink again."], ok: "It blinks. Build complete!" },
];

function help() {
  let d = document.getElementById("teleopHelp");
  if (!d) {
    d = document.createElement("div"); d.id = "teleopHelp";
    d.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:99;background:rgba(10,14,20,.92);border:1px solid rgba(120,200,255,.3);border-radius:10px;padding:10px 14px;font:12px/1.5 ui-monospace,monospace;color:#cfe;white-space:pre";
    document.body.appendChild(d);
  }
  d.textContent = "TELEOP\n1-5        step N passes\nShift+1-5  step N fails\n0 / Esc    clear";
  d.hidden = false; clearTimeout(help.t); help.t = setTimeout(() => (d.hidden = true), 4500);
}

const HOLD_MS = 25000;
function send(n, kind) {
  const real = window.__current; if (!real) return;
  window.__teleopHold = kind === "clear" ? 0 : Date.now() + HOLD_MS;   // app.js ignores backend coach/guidance meanwhile
  const cur = { ...real, onBackend: (m) => real.onBackend({ ...m, __teleop: true }) };
  const base = cur.getCoach?.() || {};
  const steps = (base.steps && base.steps.length === 5) ? base.steps : STEPS.map((s) => ({ title: s.title, action: s.action, why: s.why }));
  const project = base.project || { id: "blink", title: "Blink — external LED on Arduino Nano", steps };
  const t = STEPS[n - 1];
  const common = { phase: "teaching", steps, project, step_total: 5, board: base.board };
  const state = (idx, mistakes) => ({ ...base, ...common, step_index: idx, step: steps[idx], mistakes, awaiting_next: false });
  if (kind === "error") {
    const m = [{ id: "teleop-" + n, title: t.err[0], fix: t.err[1], severity: "warning", forced: true }];
    const st = state(n - 1, m);
    cur.onBackend({ type: "coach", ...st });
    cur.onBackend({ type: "guidance", text: `It looks like ${t.err[0].toLowerCase()}, though I could be wrong. ${t.err[1]}`, source: "verifier", coach: st });
  } else if (kind === "ok") {
    // show then clear in the same tick so the UI plays its normal "all good" transition
    cur.onBackend({ type: "coach", ...state(n - 1, [{ id: "teleop-" + n, title: t.err[0], fix: "", forced: true }]) });
    const next = Math.min(n, 4), st = state(next, []);
    cur.onBackend({ type: "coach", ...st, done: n === 5 });
    cur.onBackend({ type: "guidance", text: n < 5 ? `${t.ok} Ready for the next step: ${STEPS[n].title}.` : t.ok, source: "curriculum", coach: st });
  } else {
    cur.onBackend({ type: "coach", ...state(base.step_index || 0, []) });
  }
}

addEventListener("keydown", (e) => {
  try {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const el = e.target; if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
    if (e.key === "?") { help(); return; }
    if (e.key === "Escape" || e.code === "Digit0") { send(1, "clear"); return; }
    const m = /^Digit([1-5])$/.exec(e.code || "");
    if (!m) return;
    e.preventDefault();
    send(+m[1], e.shiftKey ? "error" : "ok");
  } catch (err) { console.warn("teleop", err); }
});
