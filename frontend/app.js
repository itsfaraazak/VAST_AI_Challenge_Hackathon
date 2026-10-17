import { createVoice } from "./voice.js";
/** CURRENT shell: hero layout, coach subtitles, voice, QR, trace/scene integration. */
const $ = (id) => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const DEMO = Q.get("demo") === "1";
const PHONE = Q.get("role") === "phone";
const BASE = location.pathname === "/app" || location.pathname.startsWith("/app/") ? "/app" : "";
document.body.classList.toggle("demo", DEMO);
document.body.classList.toggle("phone", PHONE);

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const video = $("benchVideo"), overlay = $("yoloOverlay"), feedPanel = $("feedPanel");
let coach = null, ws = null, camWs = null, sessionCode = Q.get("code"), board = "nano";
let lastYolo = null, prevMistakes = 0, projectsCache = [], thread = [], lastYoloMs = null, lastCosmos = "idle";

/* ---------- status ---------- */
function setLive(word, ok = true) {
  $("liveWord").textContent = word;
  $("chipLive").style.opacity = ok ? 1 : 0.6;
  $("phoneStatus").textContent = `${word}${sessionCode ? " · " + sessionCode : ""}`;
}
function setVerify(word, cls) {
  $("verifyWord").textContent = word;
  $("chipVerify").className = "chip " + (cls || "");
}
function setConf(v) {
  $("confWord").textContent = v == null ? "—" : Math.round(v * 100) + "%";
}
const setPipe = (t) => { const p = $("pipeLog"); if (p && t) p.textContent = t; };

/* ---------- coach subtitle + voice ---------- */
const SRC = { llm: "W&B Llama", wandb: "W&B Llama", verifier: "verifier", curriculum: "curriculum" };
function pushThread(text, user) {
  thread.push({ text, user }); thread = thread.slice(-4);
  $("thread").innerHTML = thread.slice(0, -1).slice(-3).map((m) => `<p class="${m.user ? "u" : ""}">${esc(m.text)}</p>`).join("");
}
function showCoach(text, source = "llm") {
  const el = $("coachLine");
  const prev = el.dataset.raw;
  if (prev && prev !== text) pushThread(prev, false);
  el.dataset.raw = text;
  el.innerHTML = String(text).split(/\s+/).map((w, i) => `<span class="w" style="animation-delay:${Math.min(i * 35, 1500)}ms">${esc(w)}</span>`).join(" ");
  const b = $("coachSrc"); b.textContent = SRC[source] || source; b.className = "badge " + (source === "wandb" ? "llm" : source);
}
const voice = createVoice({ onState: (st) => {
  if (st.speaking != null) $("wave").classList.toggle("on", st.speaking);
  if (st.muted != null) $("btnMute").textContent = st.muted ? "Unmute" : "Mute";
  if (st.voices) fillVoices();
} });
function fillVoices() {
  const sel = $("voiceSel"); const vs = voice.pick();
  sel.hidden = !vs.length;
  sel.innerHTML = vs.map((v) => `<option ${v.name === voice.chosen ? "selected" : ""}>${esc(v.name)}</option>`).join("");
}
fillVoices(); setTimeout(fillVoices, 800);
$("voiceSel").onchange = (e) => voice.setVoice(e.target.value);
$("btnMute").onclick = () => { voice.unlock(); voice.setMuted(!voice.muted); };
$("btnMute").textContent = voice.muted ? "Unmute" : "Mute";
addEventListener("pointerdown", () => voice.unlock(), { once: true });
addEventListener("keydown", () => voice.unlock(), { once: true });

/* ---------- coach state ---------- */
function mistakeBanner(mistakes) {
  const box = $("mistake");
  const n = mistakes.length;
  if (n) {
    const m = mistakes[0];
    box.hidden = false; box.classList.remove("fixed");
    $("mistakeTag").textContent = `${(m.severity || "error").toUpperCase()} DETECTED${n > 1 ? ` · +${n - 1} more` : ""}`;
    $("mistakeTitle").textContent = m.title || m.id;
    $("mistakeFix").textContent = m.fix ? `FIX: ${m.fix}` : "";
    if (!prevMistakes) { $("flashfx").className = "flashfx"; void $("flashfx").offsetWidth; $("flashfx").className = "flashfx red"; window.CurrentScene?.flash?.("error"); }
    setVerify(`${n} ISSUE${n > 1 ? "S" : ""}`, "bad");
  } else if (prevMistakes) {
    box.hidden = false; box.classList.add("fixed");
    $("mistakeTag").textContent = "CORRECTED";
    $("mistakeTitle").textContent = "Circuit verified ✓";
    $("mistakeFix").textContent = "";
    $("flashfx").className = "flashfx"; void $("flashfx").offsetWidth; $("flashfx").className = "flashfx green";
    window.CurrentScene?.flash?.("ok");
    window.gsap?.fromTo(box, { scale: 1.15 }, { scale: 1, duration: 0.5, ease: "back.out(2)" });
    setVerify("OK", "ok");
    setTimeout(() => { if (box.classList.contains("fixed")) box.hidden = true; }, 3200);
  } else if (!coach?.step) setVerify("—");
  prevMistakes = n;
}

const EXAMPLES = [["Blink", "blink"], ["Traffic light"], ["Button + LED"], ["Buzzer alarm"], ["Potentiometer dimmer"]];
$("examples").innerHTML = EXAMPLES.map(([t, id]) => `<button type="button" class="ex" data-t="${esc(t)}" ${id ? `data-id="${id}"` : ""}>${esc(t)}</button>`).join("");
function startProject(prompt, id) {
  prompt = (prompt || "").trim(); if (!prompt && !id) return;
  const m = { type: "coach_start", board };
  if (id) m.project_id = id;
  m.prompt = prompt;
  $("empty").classList.add("is-hidden");
  pushThread(prompt, true); $("coachUser").textContent = `You: ${prompt}`;
  send(m);
}
$("examples").addEventListener("click", (e) => { const b = e.target.closest(".ex"); if (b) startProject(b.dataset.t, b.dataset.id); });
$("startForm").addEventListener("submit", (e) => { e.preventDefault(); const v = $("startInput").value; $("startInput").value = ""; startProject(v); });
$("btnNew").onclick = () => { $("empty").classList.remove("is-hidden"); $("startInput").focus(); };

function stepCard(s, i, idx) {
  const st = i < idx ? "is-done" : i === idx ? "is-active" : "";
  const quiz = s.check || s.quiz || s.question;
  const body = i === idx ? `<div class="step__body">
    ${s.action ? `<div><b>DO</b>${esc(s.action)}</div>` : ""}
    ${s.why || s.concept ? `<div><b>WHY</b>${esc(s.why || s.concept)}</div>` : ""}
    ${s.hole_hint ? `<div class="hole"><b>HOLES</b>${esc(s.hole_hint)}</div>` : ""}
    ${quiz ? `<div class="quiz"><b>CHECK</b>${esc(typeof quiz === "string" ? quiz : quiz.q || quiz.question || "")}</div>` : ""}</div>` : "";
  return `<li class="step ${st}" data-index="${i}"><div class="step__row"><b>${i < idx ? "✓" : String(i + 1).padStart(2, "0")}</b><span class="step__t">${esc(s.title)}</span></div>${body}</li>`;
}
function applyCoach(state) {
  if (!state) return;
  coach = { ...(coach || {}), ...state };
  if (state.board) setBoardUi(state.board);
  const p = state.project || coach.project;
  const steps = (p && p.steps) || state.steps || coach.steps || [];
  const idx = state.step_index || 0;
  const total = state.step_total || steps.length;
  const teaching = state.phase === "teaching" && steps.length;
  $("projectLabel").innerHTML = p && teaching ? `Building <em>${esc(String(p.title).split("—")[0].trim())}</em> · ${board === "esp32" ? "ESP32" : "Arduino Nano"}` : "Ready to build";
  $("empty").classList.toggle("is-hidden", !!teaching);
  $("seqTitle").textContent = teaching ? p?.title || "Project" : "No project yet";
  $("seqMeta").textContent = teaching ? `Step ${Math.min(idx + 1, total)} of ${total}${state.done ? " · complete" : ""}` : "Pick a project to begin";
  $("railBar").style.width = teaching && total ? Math.min(100, ((idx + (state.done ? 1 : 0)) / total) * 100) + "%" : "0";
  if (teaching) {
    $("stepList").innerHTML = steps.map((s, i) => stepCard(s, i, idx)).join("");
    const cur = state.step || steps[idx];
    $("vizHint").textContent = cur?.title || "3D circuit";
    $("stepList").querySelector(".is-active")?.scrollIntoView?.({ block: "nearest" });
  } else {
    $("stepList").innerHTML = (state.projects || []).map((pr, i) =>
      `<li class="step" data-project="${esc(pr.id)}"><div class="step__row"><b>${String(i + 1).padStart(2, "0")}</b><span class="step__t">${esc(pr.title)}</span></div></li>`).join("");
  }
  mistakeBanner(state.mistakes || []);
  feedScene({ coach: state });
  if (!state.mistakes?.length && teaching) setVerify(state.done ? "BUILD COMPLETE" : "WATCHING", "");
}

let lastTwin = null, lastFindings = null;
function feedScene(extra = {}) {
  if (extra.twin) lastTwin = extra.twin;
  if (extra.findings) lastFindings = extra.findings;
  const c = extra.coach || coach || {};
  try {
    window.CurrentScene?.update({
      board, project: c.project, stepIndex: c.step_index || 0, twin: lastTwin, findings: lastFindings,
      steps: (c.project && c.project.steps) || c.steps, step: c.step, mistakes: c.mistakes || [],
    });
  } catch (e) { console.warn("scene update", e); }
}
function setBoardUi(b) {
  board = b === "esp32" ? "esp32" : "nano";
  document.querySelectorAll("#boardSel button").forEach((x) => x.classList.toggle("is-on", x.dataset.board === board));
  window.CurrentScene?.setBoard?.(board);
}

/* ---------- yolo overlay ---------- */
function drawYolo(msg) {
  lastYolo = msg;
  const w = overlay.parentElement.clientWidth, h = overlay.parentElement.clientHeight;
  overlay.width = w; overlay.height = h;
  const ctx = overlay.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  if (!$("togBoxes").checked) return;
  const [sh, sw] = msg?.shape || [360, 640];
  const sx = w / sw, sy = h / sh;
  const t = performance.now() / 1000;
  (msg?.boxes || []).forEach((b, i) => {
    const [x1, y1, x2, y2] = b.xyxy || [];
    if (x2 == null) return;
    const bad = b.bad;
    const col = bad ? "#ff3b57" : "#c8ff3d";
    const rx = x1 * sx, ry = y1 * sy, rw = (x2 - x1) * sx, rh = (y2 - y1) * sy;
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.shadowColor = col; ctx.shadowBlur = 10;
    const L = Math.min(18, rw / 3, rh / 3);   // AR corner brackets
    ctx.beginPath();
    [[rx, ry, 1, 1], [rx + rw, ry, -1, 1], [rx, ry + rh, 1, -1], [rx + rw, ry + rh, -1, -1]].forEach(([x, y, dx, dy]) => {
      ctx.moveTo(x + dx * L, y); ctx.lineTo(x, y); ctx.lineTo(x, y + dy * L);
    });
    ctx.stroke(); ctx.shadowBlur = 0;
    ctx.globalAlpha = 0.07 + 0.05 * Math.sin(t * 3 + i); ctx.fillStyle = col; ctx.fillRect(rx, ry, rw, rh); ctx.globalAlpha = 1;
    const label = `${b.label} ${Math.round((b.confidence || 0) * 100)}%`;
    ctx.font = "600 13px IBM Plex Mono, monospace";
    const tw = ctx.measureText(label).width + 10;
    ctx.fillStyle = "rgba(5,8,12,.85)"; ctx.fillRect(rx, Math.max(0, ry - 20), tw, 18);
    ctx.fillStyle = col; ctx.fillText(label, rx + 5, Math.max(13, ry - 6));
  });
}
addEventListener("resize", () => lastYolo && drawYolo(lastYolo));

function statusLine() {
  $("statusLine").textContent = `YOLO ${lastYoloMs == null ? "—" : Math.round(lastYoloMs) + "ms"} · cosmos ${lastCosmos}`;
}
let twinAt = 0;
function renderSeen(t) {
  const comps = t.components || [];
  twinAt = Date.now();
  $("seenList").innerHTML = comps.length ? comps.map((c) => `<span class="pchip">${esc(c.type || c.id)}</span>`).join("") : '<i class="muted">nothing detected yet</i>';
  $("twinState").textContent = "LIVE"; $("twinState").className = "live";
}
setInterval(() => { if (twinAt && Date.now() - twinAt > 15000) { $("twinState").textContent = "STALE"; $("twinState").className = "stale"; } }, 2000);
const ago = (u) => { if (!u) return ""; const d = typeof u === "number" ? (u > 1e12 ? u : u * 1000) : Date.parse(u); if (!d) return String(u); const m = Math.round((Date.now() - d) / 60000); return m < 1 ? "just now" : m < 60 ? m + "m ago" : m < 1440 ? Math.round(m / 60) + "h ago" : Math.round(m / 1440) + "d ago"; };
function renderProjects(items) {
  projectsCache = items;
  $("memCount").hidden = !items.length; $("memCount").textContent = items.length;
  $("memList").innerHTML = items.length ? items.map((p) => {
    const pct = Math.round(p.pct ?? (p.steps_total ? (p.step_index / p.steps_total) * 100 : 0));
    return `<div class="mem ${pct >= 100 ? "is-done" : ""}"><div class="mem__top"><span class="mem__title">${esc(p.title)}</span><button class="btn btn--sm" data-resume="${esc(p.key)}">Resume</button></div>
    <div class="mem__row"><div class="prog"><i style="width:${pct}%"></i></div><span class="mem__pct">${pct}%</span></div>
    <div class="mem__meta">${esc((p.board || "").toUpperCase())} · ${ago(p.updated)}${p.parts_seen?.length ? " · " + esc(p.parts_seen.slice(0, 3).join(", ")) : ""}</div></div>`;
  }).join("") : '<p class="muted pad">No saved projects yet.</p>';
}
$("memList").addEventListener("click", (e) => {
  const b = e.target.closest("[data-resume]"); if (!b) return;
  send({ type: "resume_project", key: b.dataset.resume }); tab("seq");
});
function tab(n) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("is-on", b.dataset.tab === n));
  document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("is-on", p.id === "pane-" + n));
}
$("tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) tab(b.dataset.tab); });
async function loadProjects() {
  try { const r = await fetch(`${BASE}/api/projects`); if (r.ok) { const j = await r.json(); renderProjects(Array.isArray(j) ? j : j.items || []); } } catch {}
}

/* ---------- backend message router (also used by replay) ---------- */
function onBackend(msg) {
  if (!msg) return;
  if (msg.type === "trace") { routeTrace(msg); return; }
  if (msg.coach) applyCoach(msg.coach);
  if (msg.type === "coach") applyCoach(msg);
  if (msg.type === "joined") {
    if (msg.code) { sessionCode = msg.code; renderJoin(); }
    setLive("watching");
  }
  if (msg.type === "yolo") {
    drawYolo(msg);
    lastYoloMs = msg.ms; statusLine();
    setPipe(`YOLO ${Math.round(msg.ms || 0)}ms · ${(msg.labels || []).join(", ") || "none"}\ngate: ${msg.gate?.allow_cosmos ? "ALLOW" : "SKIP"} ${msg.gate?.reason || ""}`);
    if (msg.gate?.confidence != null) setConf(msg.gate.confidence);
  }
  if (msg.type === "perception_skip") { lastCosmos = "gated"; statusLine(); setLive("aim at board", false); }
  if (msg.type === "cosmos_status") {
    if (msg.state === "calling") { lastCosmos = "thinking…"; setLive("cosmos thinking"); }
    if (msg.state === "done") { lastCosmos = (msg.ms / 1000).toFixed(1) + "s"; setLive("watching"); }
    if (msg.state === "error") { lastCosmos = "error"; setLive("cosmos error", false); }
    statusLine();
  }
  if (msg.type === "twin") {
    const t = msg.twin || {};
    if (t.confidence != null) setConf(t.confidence);
    renderSeen(t); feedScene({ twin: t, findings: msg.findings });
  }
  if (msg.type === "projects") renderProjects(msg.items || []);
  if (msg.type === "resumed" || msg.type === "project_resumed") send({ type: "projects_list" });
  if (msg.findings && msg.type !== "twin") feedScene({ findings: msg.findings });
  if (msg.type === "guidance" && msg.text) { showCoach(msg.text, msg.source || "llm"); voice.speakGuidance(msg.text, msg.source || "llm"); }
  if (msg.type === "transcript" && msg.text && msg.asr === "canary") { $("coachUser").textContent = `You: ${msg.text}`; pushThread(msg.text, true); voice.cancel(); }
  if (msg.type === "vss_upload") vssToast(msg.ok ? `Indexed in VAST VSS: ${msg.object_key || "ok"}` : `VSS upload failed: ${msg.detail || "error"}`, !msg.ok);
  if (msg.type === "asr_status" && msg.ok === false) setLive("mic miss", false);
}
function routeTrace(msg) {
  if (window.CurrentTrace) window.CurrentTrace.push(msg);
  else {
    const d = document.createElement("div");
    d.className = "tl " + (msg.status || "");
    d.innerHTML = `<b>${esc(msg.stage)}</b> ${esc(msg.label)} · ${esc(msg.sponsor)} · ${esc(msg.status)}${msg.ms != null ? " · " + msg.ms + "ms" : ""}<br>${esc(msg.detail || "")}`;
    $("traceRoot").prepend(d);
  }
}
window.CurrentApp = { onBackend, setBoardUi, speak: (t) => voice.speakGuidance(t, "coach"), get board() { return board; } };

/* ---------- send ---------- */
function send(obj) {
  if (DEMO) return window.CurrentReplay?.onClient?.(obj);
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}
$("chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("chatInput").value.trim();
  if (!t) return;
  $("coachUser").textContent = `You: ${t}`; pushThread(t, true); voice.cancel();
  $("chatInput").value = "";
  send({ type: "ask", text: t });
});
$("quick").addEventListener("click", (e) => { const b = e.target.closest(".qchip"); if (!b) return; pushThread(b.textContent, true); send({ type: "ask", text: b.dataset.q }); });
$("btnForce").onclick = () => { send({ type: "force_analyze" }); setPipe("force analyze requested…"); };
$("togBoxes").onchange = () => lastYolo && drawYolo(lastYolo);
$("stepList").addEventListener("click", (e) => {
  const li = e.target.closest(".step");
  if (!li) return;
  if (li.dataset.index != null) send({ type: "coach_step", index: +li.dataset.index });
  else if (li.dataset.project) send({ type: "coach_start", project_id: li.dataset.project, prompt: li.textContent.trim(), board });
});
document.querySelectorAll("#boardSel button").forEach((b) => b.addEventListener("click", () => {
  setBoardUi(b.dataset.board);
  if (coach?.phase === "teaching") send({ type: "coach_start", project_id: coach.project_id || "blink", prompt: coach.project?.title || "Blink", board });
}));

/* ---------- QR / join ---------- */
function joinUrl() {
  const u = new URL(location.href);
  u.search = ""; u.hash = "";
  u.searchParams.set("code", sessionCode || "");
  u.searchParams.set("role", "phone");
  return u.toString();
}
function qrSvg(url, cell) {
  try { const q = qrcode(0, "M"); q.addData(url); q.make(); return q.createSvgTag({ cellSize: cell, margin: 0, scalable: true }); } catch { return ""; }
}
function renderJoin() {
  $("codeWord").textContent = sessionCode || "······";
  if (!sessionCode) return;
  $("qrMini").innerHTML = qrSvg(joinUrl(), 2);
  $("qrBig").innerHTML = qrSvg(joinUrl(), 4);
  $("qrUrl").textContent = joinUrl();
}
$("joinBtn").onclick = () => { $("qrPop").hidden = !$("qrPop").hidden; };

/* ---------- sponsors + health ---------- */
const STATIC_SP = [
  { sponsor: "NVIDIA", name: "Cosmos", role: "vision twin", ok: true },
  { sponsor: "CoreWeave", name: "GPUs", role: "inference", ok: true },
  { sponsor: "W&B", name: "Inference", role: "coach LLM", ok: true },
  { sponsor: "VAST Data", name: "DataEngine", role: "memory", ok: true },
  { sponsor: "Cursor", name: "built with", role: "", ok: true },
];
function renderSponsors(list) {
  $("sponsors").innerHTML = `<span>POWERED BY</span>` + list.map((s) =>
    `<span class="sp" title="${esc(s.detail || s.role || "")}"><i class="dot ${s.ok === false ? "off" : ""}"></i>${esc(s.sponsor)} ${esc(s.name || "")}</span>`).join("");
}
renderSponsors(STATIC_SP);
async function loadSponsors() {
  try { const r = await fetch(`${BASE}/api/sponsors`); if (r.ok) renderSponsors(await r.json()); } catch {}
}
async function loadHealth() {
  try { const r = await fetch(`${BASE}/health`); if (r.ok) window.CurrentTrace?.setServices(await r.json()); } catch {}
}

/* ---------- connect ---------- */
async function connect() {
  const role = PHONE ? "phone" : "laptop";
  if (!sessionCode) {
    const r = await fetch(`${BASE}/api/session`, { method: "POST" });
    sessionCode = (await r.json()).code;
  }
  renderJoin();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}${BASE}/ws?code=${sessionCode}&role=${role}`);
  ws.onopen = () => { setLive("watching"); send({ type: "projects_list" }); };
  ws.onclose = () => { setLive("reconnecting", false); setTimeout(() => connect().catch(() => {}), 2000); };
  ws.onmessage = (ev) => { try { onBackend(JSON.parse(ev.data)); } catch {} };
}

/* ---------- camera ---------- */
$("armCamera").onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: PHONE ? "environment" : "user", width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    video.srcObject = stream; await video.play();
    video.classList.add("is-live"); $("feedIdle").classList.add("is-hidden");
    if (!PHONE && !DEMO) { // laptop cam: frames must come from a phone-role socket
      const proto = location.protocol === "https:" ? "wss" : "ws";
      camWs = new WebSocket(`${proto}://${location.host}${BASE}/ws?code=${sessionCode}&role=phone`);
    }
    startRecording(stream);
    frameLoop();
  } catch (e) { setLive("camera denied", false); }
};
if (PHONE && !DEMO) { $("feedIdle").querySelector("p").textContent = "Tap to start the camera"; }
let looping = false;
function frameLoop() {
  if (looping) return; looping = true;
  const c = document.createElement("canvas");
  setInterval(() => {
    const sock = PHONE ? ws : camWs;
    if (!video.videoWidth || !sock || sock.readyState !== 1) return;
    c.width = 640; c.height = Math.round(video.videoHeight * 640 / video.videoWidth) || 360;
    c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
    c.toBlob(async (b) => {
      if (!b) return;
      const u = new Uint8Array(await b.arrayBuffer()); let s = "";
      for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
      sock.send(JSON.stringify({ type: "frame", jpeg_b64: btoa(s) }));
    }, "image/jpeg", 0.72);
  }, 1000);
}

/* ---------- hold to talk ---------- */
let rec = null;
function encodeWav(chunks, rate) {
  let len = 0; chunks.forEach((c) => (len += c.length));
  const buf = new ArrayBuffer(44 + len * 2), v = new DataView(buf);
  const ws_ = (o, s) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)));
  ws_(0, "RIFF"); v.setUint32(4, 36 + len * 2, true); ws_(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  ws_(36, "data"); v.setUint32(40, len * 2, true);
  let o = 44;
  for (const c of chunks) for (let i = 0; i < c.length; i++, o += 2) { const s = Math.max(-1, Math.min(1, c[i])); v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true); }
  return buf;
}
async function recStart() {
  if (rec) return; voice.unlock(); voice.cancel();
  if (DEMO) { $("voiceBtn").classList.add("is-hot"); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = new AudioContext({ sampleRate: 16000 });
    const src = ctx.createMediaStreamSource(stream), proc = ctx.createScriptProcessor(4096, 1, 1), chunks = [];
    proc.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    src.connect(proc); proc.connect(ctx.destination);
    rec = { stream, ctx, proc, chunks };
    $("voiceBtn").classList.add("is-hot"); setLive("listening");
  } catch { setLive("mic denied", false); }
}
async function recStop() {
  $("voiceBtn").classList.remove("is-hot");
  if (DEMO) return window.CurrentReplay?.onClient?.({ type: "ask", text: "why does the LED need a resistor?" });
  if (!rec) return;
  const { stream, ctx, proc, chunks } = rec; rec = null;
  proc.disconnect(); stream.getTracks().forEach((t) => t.stop());
  const rate = ctx.sampleRate; await ctx.close();
  if (!chunks.length) return;
  const u = new Uint8Array(encodeWav(chunks, rate)); let s = "";
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  setLive("transcribing"); send({ type: "audio", wav_b64: btoa(s) });
}
const mic = $("voiceBtn");
["mousedown", "touchstart"].forEach((n) => mic.addEventListener(n, (e) => { e.preventDefault(); recStart(); }));
["mouseup", "touchend", "mouseleave"].forEach((n) => mic.addEventListener(n, (e) => { e.preventDefault(); recStop(); }));

/* ---------- misc ---------- */
setInterval(() => { $("feedClock").textContent = new Date().toLocaleTimeString("en-GB", { hour12: false }); }, 1000);
window.CurrentTrace?.mount($("traceRoot"));
window.CurrentScene?.mount($("scene3d"));
if (window.CurrentScene) feedScene();
else setTimeout(() => {   // fallback: legacy Nano viewer
  if (window.CurrentScene) { window.CurrentScene.mount($("scene3d")); feedScene(); return; }
  $("scene3d").innerHTML = '<div id="nano3d" style="width:100%;height:100%"></div>';
  const t = document.createElement("script"); t.src = "https://unpkg.com/three@0.160.0/build/three.min.js";
  t.onload = () => { const s = document.createElement("script"); s.src = "./nano3d.js"; document.body.appendChild(s); };
  document.body.appendChild(t);
}, 1500);
loadSponsors(); loadHealth(); loadProjects(); setInterval(loadHealth, 30000);

if (DEMO) {
  sessionCode = sessionCode || "DEMO42"; renderJoin(); setLive("watching");
  import("./replay.js").catch((e) => console.error("replay", e));
} else {
  connect().catch(() => setLive("backend unreachable", false));
}


/* ---------- session recording -> VAST VSS ---------- */
let mrec = null, mChunks = [], mBytes = 0, mMaxBytes = 20 * 1024 * 1024, uploading = false;
const REC_MAX_MS = 90000;
function vssToast(text, bad = false, sticky = false) {
  const t = $("vssToast"); t.textContent = text; t.classList.toggle("bad", !!bad); t.hidden = false;
  clearTimeout(vssToast._t); if (!sticky) vssToast._t = setTimeout(() => { t.hidden = true; }, 9000);
}
async function startRecording(stream) {
  if (DEMO || mrec || !window.MediaRecorder) return;
  try {
    const r = await fetch(`${BASE}/api/vss-limits`);
    const mb = (await r.json()).max_mb;
    if (mb) mMaxBytes = Math.floor(mb * 0.85 * 1024 * 1024);
  } catch {}
  try {
    const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
    mrec = new MediaRecorder(stream, { ...(mime ? { mimeType: mime } : {}), videoBitsPerSecond: 800000 });
    mrec.ondataavailable = (e) => {
      if (!e.data.size) return;
      mChunks.push(e.data); mBytes += e.data.size;
      // dropping mid-stream chunks would corrupt the webm, so stop at the cap instead
      if (mChunks.length >= REC_MAX_MS / 1000 || mBytes >= mMaxBytes) { try { mrec.stop(); } catch {} $("btnVss").classList.remove("is-rec"); }
    };
    mrec.start(1000);
    $("btnVss").classList.add("is-rec");
  } catch (e) { console.warn("recorder", e); mrec = null; }
}
function sessionBlob() { return new Blob(mChunks, { type: "video/webm" }); }
async function sendSession(beacon = false) {
  if (uploading) return;
  if (DEMO) {
    uploading = true; vssToast("Uploading session to VAST VSS…", false, true);
    return setTimeout(() => { uploading = false; vssToast("Indexed in VAST VSS: current-live/DEMO42/session.webm"); }, 1400);
  }
  if (!mChunks.length) return vssToast("Nothing recorded yet. Start the camera first.", true);
  const blob = sessionBlob(), url = `${BASE}/api/session/${sessionCode}/upload`;
  if (beacon) { navigator.sendBeacon?.(url, blob); return; }
  uploading = true; vssToast(`Uploading ${(blob.size / 1e6).toFixed(1)} MB to VAST VSS…`, false, true);
  try {
    const fd = new FormData(); fd.append("file", blob, "session.webm");
    const r = await fetch(url, { method: "POST", body: fd });
    const j = await r.json();
    vssToast(j.ok ? `Indexed in VAST VSS: ${j.object_key || "ok"}` : `VSS upload failed: ${j.detail || j.status}`, !j.ok);
  } catch (e) { vssToast("VSS upload failed: network", true); }
  uploading = false;
}
$("btnVss").onclick = () => sendSession();
let autoSent = false;
addEventListener("pagehide", () => { if (!autoSent && !DEMO && !uploading && mBytes > 50000) { autoSent = true; sendSession(true); } });
