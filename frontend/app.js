/**
 * CURRENT — proactive Blink teacher UI.
 * Curriculum + tips from backend coach; vision via Cosmos; voice via Canary ASR.
 */
const BASE =
  location.pathname === "/app" || location.pathname.startsWith("/app/")
    ? "/app"
    : "";

const thread = document.getElementById("chatThread");
const form = document.getElementById("chatForm");
const input = document.getElementById("chatInput");
const voiceBtn = document.getElementById("voiceBtn");
const stepList = document.getElementById("stepList");
const stepProgress = document.getElementById("stepProgress");
const stepTotal = document.getElementById("stepTotal");
const video = document.getElementById("benchVideo");
const feedIdle = document.getElementById("feedIdle");
const armCamera = document.getElementById("armCamera");
const feedClock = document.getElementById("feedClock");
const statusEl = document.querySelector(".top__status");
const cosmosPanel = document.getElementById("cosmosPanel");
const cosmosBadge = document.getElementById("cosmosBadge");
const twinPanel = document.getElementById("twinPanel");
const projectLabel = document.getElementById("projectLabel");
const vizHint = document.getElementById("vizHint");
const vizLegend = document.getElementById("vizLegend");
const btnBlink = document.getElementById("btnBlink");
const btnNext = document.getElementById("btnNext");
const overlay = document.getElementById("yoloOverlay");
const pipeLog = document.getElementById("pipeLog");
const togBoxes = document.getElementById("togBoxes");
const togVerbose = document.getElementById("togVerbose");
const btnForce = document.getElementById("btnForce");

let coach = null;
let ws = null;
let sessionCode = null;
let mediaStream = null;
let sendingFrames = false;
let frameCount = 0;
let lastYolo = null;

function setPipeStage(active, extra = "") {
  document.querySelectorAll(".pipe").forEach((el) => {
    el.classList.toggle("is-on", el.dataset.stage === active);
  });
  if (pipeLog && (togVerbose?.checked ?? true)) {
    pipeLog.textContent = extra || pipeLog.textContent;
  }
}

function drawYoloBoxes(msg) {
  lastYolo = msg;
  if (!overlay || !video) return;
  const show = togBoxes?.checked ?? true;
  const w = video.clientWidth || 0;
  const h = video.clientHeight || 0;
  if (!w || !h) return;
  overlay.width = w;
  overlay.height = h;
  const ctx = overlay.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  if (!show) return;
  const boxes = msg?.boxes || [];
  const shape = msg?.shape; // [H, W] from YOLO
  const srcH = shape?.[0] || video.videoHeight || h;
  const srcW = shape?.[1] || video.videoWidth || w;
  const sx = w / srcW;
  const sy = h / srcH;
  boxes.forEach((b) => {
    const [x1, y1, x2, y2] = b.xyxy || [];
    if (x2 == null) return;
    const rx = x1 * sx;
    const ry = y1 * sy;
    const rw = (x2 - x1) * sx;
    const rh = (y2 - y1) * sy;
    ctx.strokeStyle = "#d6ff4b";
    ctx.lineWidth = 2;
    ctx.strokeRect(rx, ry, rw, rh);
    ctx.fillStyle = "rgba(12,14,16,0.75)";
    const label = `${b.label} ${Math.round((b.confidence || 0) * 100)}%`;
    ctx.font = "12px IBM Plex Mono, monospace";
    const tw = ctx.measureText(label).width + 8;
    ctx.fillRect(rx, Math.max(0, ry - 18), tw, 16);
    ctx.fillStyle = "#d6ff4b";
    ctx.fillText(label, rx + 4, Math.max(12, ry - 5));
  });
}

function setCosmosHud(text, hot = false) {
  if (cosmosPanel) {
    cosmosPanel.textContent = text;
    cosmosPanel.classList.toggle("is-hot", hot);
  }
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function addMessage(role, text) {
  const who =
    role === "agent" ? "Current" : role === "system" ? "Alert" : "You";
  const el = document.createElement("article");
  el.className = `msg msg--${role}`;
  el.innerHTML = `
    <div class="msg__who">${who}</div>
    <p class="msg__body">${text}</p>
  `;
  thread.appendChild(el);
  thread.scrollTop = thread.scrollHeight;
}

function setStatus(label, ok = true) {
  if (!statusEl) return;
  statusEl.innerHTML = `<span class="top__dot" aria-hidden="true"></span>${label}`;
  statusEl.style.opacity = ok ? "1" : "0.7";
}

function applyCoach(state) {
  if (!state) return;
  coach = state;
  const project = state.project;

  if (project) {
    projectLabel.innerHTML = `Building <em>${escapeHtml(project.title.split("—")[0].trim())}</em><span class="top__sep" aria-hidden="true"> · </span>Arduino Nano`;
  } else {
    projectLabel.textContent = "What do you want to build?";
  }

  const idx = state.step_index || 0;
  const total = state.step_total || (state.steps || []).length || 0;
  stepProgress.textContent = total ? String(idx + 1) : "—";
  stepTotal.textContent = total ? String(total) : "—";

  if (state.phase === "teaching" && (state.step || state.steps)) {
    if (state.steps) window.__BLINK_STEPS = state.steps;
    renderTeachingSteps(state);
    const step = state.step || (state.steps || [])[state.step_index || 0];
    if (step) {
      syncNano3d(step);
      vizHint.textContent = step.title;
      vizLegend.textContent = step.action || step.teach || "";
    }
  } else {
    stepList.innerHTML = (state.projects || [])
      .map(
        (p, i) => `
      <li class="step ${i === 0 ? "is-active" : ""}" data-id="${escapeHtml(p.id)}">
        <span class="step__index">${String(i + 1).padStart(2, "0")}</span>
        <p class="step__title">${escapeHtml(p.title)}</p>
        <p class="step__hint">${escapeHtml(p.pitch)}</p>
      </li>`
      )
      .join("");
  }
}

function renderTeachingSteps(state) {
  const steps =
    state.steps ||
    window.__BLINK_STEPS ||
    [
      { id: "orient", title: "Orient the Nano and breadboard" },
      { id: "led", title: "Seat the LED (polarity matters)" },
      { id: "resistor", title: "Add a 220Ω series resistor" },
      { id: "gnd", title: "Close the circuit to GND" },
      { id: "flash", title: "Power up and run Blink" },
    ];
  const active = state.step_index || 0;
  stepList.innerHTML = steps
    .map((step, i) => {
      const st =
        i < active ? "is-done" : i === active ? "is-active" : "";
      const hint =
        i === active && state.step
          ? state.step.teach || state.step.action || ""
          : step.teach || step.hint || "";
      return `
      <li class="step ${st}" data-index="${i}" data-id="${escapeHtml(step.id)}">
        <span class="step__index">${String(i + 1).padStart(2, "0")}</span>
        <p class="step__title">${escapeHtml(step.title)}</p>
        <p class="step__hint">${escapeHtml(hint)}</p>
      </li>`;
    })
    .join("");
}

function syncNano3d(step) {
  if (window.CURRENT_NANO3D && step) {
    window.CURRENT_NANO3D.setStep(step);
  }
}

function speak(text) {
  if (!window.speechSynthesis || !text) return;
  const u = new SpeechSynthesisUtterance(text);
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

async function connectBackend() {
  const r = await fetch(`${BASE}/api/session`, { method: "POST" });
  if (!r.ok) throw new Error("session failed");
  sessionCode = (await r.json()).code;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(
    `${proto}://${location.host}${BASE}/ws?code=${sessionCode}&role=phone`
  );
  ws.onopen = () => setStatus(`Watching · ${sessionCode}`);
  ws.onclose = () => setStatus("Disconnected", false);
  ws.onerror = () => setStatus("Socket error", false);
  ws.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    onBackend(msg);
  };
}

function send(obj) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

function onBackend(msg) {
  if (msg.coach) applyCoach(msg.coach);
  if (msg.type === "coach") applyCoach(msg);

  if (msg.type === "joined" && msg.coach) {
    applyCoach(msg.coach);
  }

  if (msg.type === "yolo") {
    setPipeStage(
      "yolo",
      `YOLO ${msg.ok ? "ok" : "fail"} · ${Math.round(msg.ms || 0)} ms\n` +
        `labels: ${(msg.labels || []).join(", ") || "(none)"}\n` +
        `gate: ${msg.gate?.allow_cosmos ? "ALLOW Cosmos" : "SKIP Cosmos"} — ${msg.gate?.reason || "?"}\n` +
        `${msg.gate?.detail || ""}`
    );
    drawYoloBoxes(msg);
    if (cosmosBadge && !String(cosmosBadge.textContent).includes("calling")) {
      cosmosBadge.textContent = `yolo · ${Math.round(msg.ms || 0)} ms`;
    }
  }

  if (msg.type === "perception_skip") {
    setPipeStage(
      "gate",
      `GATE blocked Cosmos\nreason: ${msg.reason}\n${msg.detail || ""}\n` +
        `yolo ${(msg.labels || []).join(", ") || "(none)"} · ${msg.yolo_ms ?? "—"} ms\n` +
        `called_cosmos: false`
    );
    if (cosmosBadge) cosmosBadge.textContent = "cosmos · gated";
    setCosmosHud(
      `SKIP Cosmos — ${msg.reason}\n${msg.detail || ""}\n` +
        `YOLO: ${(msg.labels || []).join(", ") || "(none)"} · ${msg.yolo_ms ?? "—"} ms`,
      true
    );
    setStatus("Gated — aim at board", false);
  }

  if (msg.type === "cosmos_status") {
    if (msg.state === "queued_force") {
      setPipeStage("cosmos", "Force analyze queued…");
      setStatus("Force queued");
    } else if (msg.state === "calling") {
      setPipeStage(
        "cosmos",
        `COSMOS calling (real NIM)\nyolo ${msg.yolo_ms ?? "—"} ms · ok=${msg.yolo_ok}\n` +
          `labels: ${(msg.labels || []).join(", ") || "(none)"}\n` +
          `gate: ${msg.gate?.reason || "allow"} · forced=${!!msg.forced}`
      );
      if (cosmosBadge) cosmosBadge.textContent = "cosmos · calling…";
      setCosmosHud(
        `COSMOS calling…\nyolo ${msg.yolo_ms ?? "—"} ms` +
          (msg.labels?.length ? `\nlabels: ${msg.labels.join(", ")}` : "") +
          `\ncalled_cosmos: true`,
        true
      );
      setStatus("Cosmos running…");
    } else if (msg.state === "done") {
      setPipeStage(
        "cosmos",
        `COSMOS done · ${Math.round(msg.ms || 0)} ms · scene=${msg.scene || "?"}`
      );
      if (cosmosBadge)
        cosmosBadge.textContent = `cosmos · ${Math.round(msg.ms || 0)} ms`;
      setCosmosHud(
        `COSMOS ok · ${Math.round(msg.ms || 0)} ms` +
          (msg.retries ? ` · retries ${msg.retries}` : "") +
          (msg.model ? `\nmodel: ${msg.model}` : "") +
          `\nscene: ${msg.scene || "?"}`,
        false
      );
      setStatus(`Cosmos ${Math.round(msg.ms || 0)} ms`);
    } else if (msg.state === "error") {
      setPipeStage("cosmos", `COSMOS error · ${msg.error}`);
      if (cosmosBadge) cosmosBadge.textContent = "cosmos · error";
      setCosmosHud(
        `COSMOS error · ${msg.error || "failed"} · http ${msg.http ?? "—"} · ${msg.ms ?? "—"} ms`,
        true
      );
      setStatus("Cosmos error", false);
    }
  }

  if (msg.type === "guidance" && msg.text) {
    setPipeStage("coach", `Coach tip · ${msg.source || "llm"}`);
    const src = msg.source || "llm";
    const ms = msg.ms != null ? ` · ${Math.round(msg.ms)} ms` : "";
    addMessage(
      "agent",
      escapeHtml(msg.text) +
        ` <span style="opacity:.55;font-size:.85em">[${escapeHtml(src)}${ms}]</span>`
    );
    speak(msg.text);
  }

  if (msg.type === "twin") {
    const twin = msg.twin || {};
    const timing = msg.timing || {};
    if (twinPanel) twinPanel.textContent = JSON.stringify(twin, null, 2);
    const comps = (twin.components || [])
      .map((c) => `${c.id}:${c.type}`)
      .join(", ");
    const places = (twin.placements || [])
      .map((p) => `${p.id}@${p.anode_hole || p.holes || "?"}`)
      .join(", ");
    setCosmosHud(
      `COSMOS ok · ${Math.round(timing.cosmos_ms || 0)} ms` +
        (timing.llm_ms != null
          ? ` · coach ${Math.round(timing.llm_ms)} ms`
          : "") +
        `\nscene: ${twin.scene || "?"} · ${twin.observation || ""}` +
        `\ncomponents: ${comps || "(none)"}` +
        (places ? `\nholes: ${places}` : ""),
      twin.scene === "other"
    );
    setStatus(
      twin.scene === "other"
        ? "Not a bench scene"
        : `Twin · ${comps || "empty"}`
    );
    setPipeStage(
      "coach",
      twin.observation
        ? `Saw: ${twin.observation}`
        : `Twin components: ${comps || "(none)"}`
    );
  }

  if (msg.type === "perception_error") {
    addMessage(
      "system",
      "Cosmos could not parse a circuit twin — fill the frame with the breadboard."
    );
  }

  if (msg.type === "transcript" && msg.text) {
    if (msg.asr === "canary") {
      addMessage(
        "user",
        escapeHtml(msg.text) +
          ` <span style="opacity:.55;font-size:.85em">[canary${msg.ms != null ? ` · ${Math.round(msg.ms)} ms` : ""}]</span>`
      );
    }
  }

  if (msg.type === "asr_status" && msg.ok === false) {
    setStatus("Canary ASR miss", false);
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", escapeHtml(text));
  input.value = "";
  autoGrow();
  send({ type: "ask", text });
});

input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

function autoGrow() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 96)}px`;
}

btnBlink?.addEventListener("click", () => {
  send({ type: "coach_start", project_id: "blink" });
});

btnNext?.addEventListener("click", () => {
  send({ type: "ask", text: "next" });
});

btnForce?.addEventListener("click", () => {
  send({ type: "force_analyze" });
  setPipeStage("cosmos", "Force Cosmos requested…");
});

togBoxes?.addEventListener("change", () => {
  if (lastYolo) drawYoloBoxes(lastYolo);
});

window.addEventListener("resize", () => {
  if (lastYolo) drawYoloBoxes(lastYolo);
});

stepList.addEventListener("click", (e) => {
  const li = e.target.closest(".step");
  if (!li) return;
  const idx = li.dataset.index;
  if (idx != null) {
    send({ type: "coach_step", index: Number(idx) });
  } else if (li.dataset.id === "blink") {
    send({ type: "coach_start", project_id: "blink" });
  }
});

/* -------- Canary hold-to-talk (PCM → WAV) -------- */
let rec = null;

function encodeWav(floatChunks, sampleRate) {
  let len = 0;
  floatChunks.forEach((c) => (len += c.length));
  const pcm = new Int16Array(len);
  let off = 0;
  for (const chunk of floatChunks) {
    for (let i = 0; i < chunk.length; i++) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      pcm[off++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
  }
  const buffer = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buffer);
  const writeStr = (o, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + pcm.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, pcm.length * 2, true);
  let p = 44;
  for (let i = 0; i < pcm.length; i++, p += 2) view.setInt16(p, pcm[i], true);
  return buffer;
}

async function startCanaryRec() {
  if (rec) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = new AudioContext({ sampleRate: 16000 });
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    proc.onaudioprocess = (e) => {
      chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    src.connect(proc);
    proc.connect(ctx.destination);
    rec = { stream, ctx, proc, chunks };
    voiceBtn.classList.add("is-hot");
    setStatus("Listening (Canary)…");
  } catch (err) {
    addMessage(
      "system",
      `Mic denied (${err.name}). Allow microphone, or type instead.`
    );
  }
}

async function stopCanaryRec() {
  if (!rec) return;
  const { stream, ctx, proc, chunks } = rec;
  rec = null;
  voiceBtn.classList.remove("is-hot");
  try {
    proc.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    const rate = ctx.sampleRate || 16000;
    await ctx.close();
    if (!chunks.length) {
      setStatus("No audio caught", false);
      return;
    }
    const wav = encodeWav(chunks, rate);
    const bytes = new Uint8Array(wav);
    let s = "";
    const step = 0x8000;
    for (let i = 0; i < bytes.length; i += step) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    }
    setStatus("Transcribing…");
    send({ type: "audio", wav_b64: btoa(s) });
  } catch (err) {
    addMessage("system", `Voice capture failed: ${err.message}`);
  }
}

voiceBtn.addEventListener("mousedown", (e) => {
  e.preventDefault();
  startCanaryRec();
});
voiceBtn.addEventListener("mouseup", (e) => {
  e.preventDefault();
  stopCanaryRec();
});
voiceBtn.addEventListener("mouseleave", () => {
  if (rec) stopCanaryRec();
});
voiceBtn.addEventListener("touchstart", (e) => {
  e.preventDefault();
  startCanaryRec();
});
voiceBtn.addEventListener("touchend", (e) => {
  e.preventDefault();
  stopCanaryRec();
});

/* Camera */
armCamera.addEventListener("click", async () => {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    video.srcObject = mediaStream;
    await video.play();
    video.classList.add("is-live");
    feedIdle.classList.add("is-hidden");
    addMessage(
      "agent",
      "Camera armed — point at the breadboard so Cosmos can see each wire."
    );
    startFrameLoop();
  } catch (err) {
    addMessage(
      "system",
      `Could not open the camera (${err.name}). Allow permission or pick Continuity Camera.`
    );
  }
});

function startFrameLoop() {
  if (sendingFrames) return;
  sendingFrames = true;
  const canvas = document.createElement("canvas");
  setInterval(() => {
    if (!video.videoWidth || !ws || ws.readyState !== 1) return;
    const w = 640;
    const h = Math.round((video.videoHeight * w) / video.videoWidth) || 360;
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d").drawImage(video, 0, 0, w, h);
    canvas.toBlob(
      async (blob) => {
        if (!blob) return;
        const buf = await blob.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let s = "";
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
          s += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        }
        frameCount += 1;
        if (
          frameCount % 2 === 1 &&
          cosmosBadge &&
          !String(cosmosBadge.textContent).includes("calling")
        ) {
          cosmosBadge.textContent = `frames · ${frameCount}`;
        }
        send({ type: "frame", jpeg_b64: btoa(s) });
      },
      "image/jpeg",
      0.72
    );
  }, 1000);
}

function tickClock() {
  const now = new Date();
  feedClock.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
}

tickClock();
setInterval(tickClock, 1000);

connectBackend().catch((err) => {
  setStatus("Backend unreachable", false);
  addMessage("system", `Backend connect failed: ${err.message}`);
});
