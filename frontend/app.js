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
let lastYolo = null, prevMistakes = 0, voiceOn = true, userGesture = false, lastSpoken = "";

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
function showCoach(text) {
  const el = $("coachLine");
  el.innerHTML = String(text).split(/\s+/).map((w, i) => `<span class="w" style="animation-delay:${Math.min(i * 40, 1800)}ms">${esc(w)}</span>`).join(" ");
}
function speak(text) {
  if (!voiceOn || !userGesture || !window.speechSynthesis || !text || text === lastSpoken) return;
  lastSpoken = text;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.05;
    speechSynthesis.speak(u);
  } catch {}
}
addEventListener("pointerdown", () => { userGesture = true; }, { once: true });
$("btnVoice").onclick = () => {
  voiceOn = !voiceOn; userGesture = true;
  $("btnVoice").classList.toggle("is-off", !voiceOn);
  $("btnVoice").textContent = voiceOn ? "🔊 Voice" : "🔇 Muted";
  if (!voiceOn) speechSynthesis?.cancel();
};

/* ---------- coach state ---------- */
/* Calm, non-blocking note. Vision is often wrong, so: debounce, never cover the 3D view, one tap to dismiss. */
const dismissedIds = new Set(); let issueSince = 0, issueKey = "", okTimer = null;
function mistakeBanner(mistakes) {
  const box = $("mistake");
  const list = (mistakes || []).filter((m) => !dismissedIds.has(m.id));
  const key = list.map((m) => m.id).join(",");
  if (key !== issueKey) { issueKey = key; issueSince = list.length ? Date.now() : 0; }
  const stable = list.length && (list.some((m) => m.forced) || Date.now() - issueSince >= 5000);   // must persist 5 s before we say anything
  if (stable) {
    const m = list[0];
    box.hidden = false; box.classList.remove("fixed"); clearTimeout(okTimer);
    $("mistakeTag").textContent = "POSSIBLE ISSUE";
    $("mistakeTitle").textContent = m.title || m.id;
    $("mistakeFix").innerHTML = (m.fix ? esc(m.fix) + " " : "") + '<button type="button" class="note__x" id="noteX">Looks fine to me ✕</button>';
    $("noteX").onclick = () => { list.forEach((x) => dismissedIds.add(x.id)); box.hidden = true; send({ type: "override", action: "dismiss" }); };
    setVerify("CHECK", "bad");
  } else if (!list.length && !box.hidden && !box.classList.contains("fixed") && prevMistakes) {
    box.classList.add("fixed");
    $("mistakeTag").textContent = "ALL GOOD";
    $("mistakeTitle").textContent = "Looks right ✓";
    $("mistakeFix").textContent = "";
    setVerify("OK", "ok");
    okTimer = setTimeout(() => { box.hidden = true; box.classList.remove("fixed"); }, 2500);
  } else if (!list.length && !coach?.step) setVerify("—");
  else if (!list.length && !box.classList.contains("fixed")) box.hidden = true;
  prevMistakes = list.length;
}
setInterval(() => mistakeBanner(coach?.mistakes || []), 1000);   // re-evaluate the debounce even without new messages

function applyCoach(state) {
  if (!state) return;
  coach = { ...(coach || {}), ...state };
  if (state.board) setBoardUi(state.board);
  const p = state.project;
  $("projectLabel").innerHTML = p
    ? `Building <em>${esc(p.title.split("—")[0].trim())}</em> · ${board === "esp32" ? "ESP32" : "Arduino Nano"}`
    : "What do you want to build?";
  const steps = state.steps || coach.steps || [];
  const idx = state.step_index || 0;
  const total = state.step_total || steps.length;
  $("railBar").style.width = total ? ((idx + (state.done ? 1 : 0.4)) / total) * 100 + "%" : "0";
  if (state.phase === "teaching" && steps.length) {
    $("stepList").innerHTML = steps.map((s, i) =>
      `<li class="step ${i < idx ? "is-done" : i === idx ? "is-active" : "is-next"}" data-index="${i}" title="${esc(s.action || "")}"><b>${String(i + 1).padStart(2, "0")}</b><span class="st"><i>${esc(s.title)}</i><em>${esc(s.action || s.concept || "")}</em></span></li>`).join("");
    $("btnNext")?.classList.toggle("ready", !!state.awaiting_next);
    const cur = state.step || steps[idx];
    const why = cur?.why || cur?.concept;
    $("whyBox").innerHTML = why ? `<b>WHY ›</b> ${esc(why)}` : "";
    $("vizHint").textContent = cur?.title || "3D circuit";
  } else {
    $("stepList").innerHTML = (state.projects || []).map((pr, i) =>
      `<li class="step" data-project="${esc(pr.id)}"><b>${String(i + 1).padStart(2, "0")}</b>${esc(pr.title)}</li>`).join("");
    $("whyBox").textContent = "";
  }
  mistakeBanner(state.mistakes || []);
  feedScene({ coach: state });
  if (!state.mistakes?.length && state.phase === "teaching") setVerify(state.step_index >= total - 1 && state.done ? "BUILD COMPLETE" : "WATCHING", "");
}

let lastTwin = null, lastFindings = null;
function feedScene(extra = {}) {
  if (extra.twin) lastTwin = extra.twin;
  if (extra.findings) lastFindings = extra.findings;
  const c = extra.coach || coach || {};
  try {
    window.CurrentScene?.update({
      board, project: c.project, stepIndex: c.step_index || 0, twin: lastTwin, findings: lastFindings,
      steps: c.steps, step: c.step, mistakes: c.mistakes || [],
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
  const w = feedPanel.clientWidth, h = feedPanel.clientHeight;
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
    setPipe(`YOLO ${Math.round(msg.ms || 0)}ms · ${(msg.labels || []).join(", ") || "none"}\ngate: ${msg.gate?.allow_cosmos ? "ALLOW" : "SKIP"} ${msg.gate?.reason || ""}`);
    if (msg.gate?.confidence != null) setConf(msg.gate.confidence);
  }
  if (msg.type === "perception_skip") { $("cosmosBadge").textContent = "cosmos · gated"; setLive("aim at board", false); }
  if (msg.type === "cosmos_status") {
    const b = $("cosmosBadge");
    if (msg.state === "calling") { b.textContent = "cosmos · calling…"; setLive("cosmos thinking"); }
    if (msg.state === "done") { b.textContent = `cosmos · ${Math.round(msg.ms || 0)}ms`; setLive("watching"); }
    if (msg.state === "error") { b.textContent = "cosmos · error"; setLive("cosmos error", false); }
  }
  if (msg.type === "twin") {
    const t = msg.twin || {};
    if (t.confidence != null) setConf(t.confidence);
    feedScene({ twin: t, findings: msg.findings });
  }
  if (msg.findings && msg.type !== "twin") feedScene({ findings: msg.findings });
  if (msg.type === "guidance" && msg.text) { showCoach(msg.text); speak(msg.text); }
  if (msg.type === "transcript" && msg.text && msg.asr === "canary") $("coachUser").textContent = `You: ${msg.text}`;
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
window.CurrentApp = { onBackend, setBoardUi, speak, get board() { return board; } };

/* ---------- send ---------- */
function send(obj) {
  if (DEMO) return window.CurrentReplay?.onClient?.(obj);
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}
$("chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("chatInput").value.trim();
  if (!t) return;
  $("coachUser").textContent = `You: ${t}`;
  $("chatInput").value = "";
  send({ type: "ask", text: t });
});
$("btnNext").onclick = () => send({ type: "ask", text: "next" });
$("btnForce").onclick = () => { send({ type: "force_analyze" }); setPipe("force analyze requested…"); };
$("togBoxes").onchange = () => lastYolo && drawYolo(lastYolo);
$("stepList").addEventListener("click", (e) => {
  const li = e.target.closest(".step");
  if (!li) return;
  if (li.dataset.index != null) send({ type: "coach_step", index: +li.dataset.index });
  else if (li.dataset.project) send({ type: "coach_start", project_id: li.dataset.project, board });
});
document.querySelectorAll("#boardSel button").forEach((b) => b.addEventListener("click", () => {
  setBoardUi(b.dataset.board);
  send({ type: "coach_start", project_id: "blink", board });
}));
$("btnTrace").onclick = () => $("drawer").classList.toggle("open");
$("drawerClose").onclick = () => $("drawer").classList.remove("open");

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
  ws.onopen = () => setLive("watching");
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
  if (rec) return; userGesture = true;
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
loadSponsors(); loadHealth(); setInterval(loadHealth, 30000);

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

/* hook for demo teleop (frontend/teleop.js) */
window.__current = { onBackend, getCoach: () => coach };
