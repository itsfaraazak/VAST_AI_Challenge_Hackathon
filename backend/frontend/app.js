import { WokwiClient } from "./wokwi-client.js";

const STEPS = [
  {
    id: "led",
    title: "Seat the LED across two rows",
    hint: "Long leg toward the signal side. Leave space for the resistor.",
  },
  {
    id: "resistor",
    title: "Drop in a 220Ω resistor",
    hint: "Series with the LED. No resistor = fried diode.",
  },
  {
    id: "signal",
    title: "Jump signal to Nano D13",
    hint: "Match the pin your sketch uses. Wrong pin is the classic miss.",
  },
  {
    id: "gnd",
    title: "Tie the cathode rail to GND",
    hint: "Common ground closes the loop.",
  },
  {
    id: "flash",
    title: "Flash Blink and watch the beat",
    hint: "If it still sits dark, ask CURRENT what changed.",
  },
];

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
const feedSource = document.getElementById("feedSource");
const cameraSelect = document.getElementById("cameraSelect");
const cameraSelectLive = document.getElementById("cameraSelectLive");
const liveBar = document.getElementById("liveBar");

let clips = [];
let activeVideo = "";
let streamUrl = "";
let lastBucket = -1;
let tickGen = 0;
let chatBusy = false;

function renderSteps(steps) {
  const rows = steps && steps.length ? steps : STEPS.map((step, i) => ({
    ...step,
    state: i === 0 ? "active" : "pending",
  }));
  const active = rows.findIndex((step) => step.state === "active");
  stepTotal.textContent = String(rows.length);
  stepProgress.textContent = String(active >= 0 ? active + 1 : rows.length);
  stepList.innerHTML = rows
    .map((step) => {
      const meta = STEPS.find((item) => item.id === step.id);
      const state =
        step.state === "done" ? "is-done" : step.state === "active" ? "is-active" : "";
      const index = STEPS.findIndex((item) => item.id === step.id);
      return `
      <li class="step ${state}" data-id="${step.id}">
        <span class="step__index">${String((index >= 0 ? index : 0) + 1).padStart(2, "0")}</span>
        <p class="step__title">${escapeHtml(step.title)}</p>
        <p class="step__hint">${escapeHtml(meta ? meta.hint : "")}</p>
      </li>
    `;
    })
    .join("");
}

function addMessage(role, text) {
  const who =
    role === "agent" ? "Current" : role === "system" ? "Alert" : "You";
  const el = document.createElement("article");
  el.className = `msg msg--${role}`;
  const whoEl = document.createElement("div");
  whoEl.className = "msg__who";
  whoEl.textContent = who;
  const body = document.createElement("p");
  body.className = "msg__body";
  body.textContent = text;
  el.append(whoEl, body);
  thread.appendChild(el);
  thread.scrollTop = thread.scrollHeight;
}

function speak(text) {
  if (!window.speechSynthesis || !text) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || chatBusy) return;
  addMessage("user", text);
  input.value = "";
  autoGrow();
  chatBusy = true;
  try {
    const response = await fetch("api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ original_video: activeVideo, message: text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error("chat failed");
    addMessage("agent", data.answer || "");
    if (data.seek_sec != null && !Number.isNaN(Number(data.seek_sec))) {
      video.currentTime = Number(data.seek_sec);
      showFeed();
      video.play().catch(() => {});
    }
  } catch {
    addMessage("system", "Chat did not come back. Try the question again.");
  } finally {
    chatBusy = false;
  }
});

input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function autoGrow() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 96)}px`;
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/* Voice — hold to talk via Web Speech API when available */
const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;

if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    input.value = transcript.trim();
    autoGrow();
  };

  recognition.onend = () => {
    listening = false;
    voiceBtn.classList.remove("is-hot");
    if (input.value.trim()) form.requestSubmit();
  };

  recognition.onerror = () => {
    listening = false;
    voiceBtn.classList.remove("is-hot");
  };

  const startListen = () => {
    if (listening) return;
    listening = true;
    voiceBtn.classList.add("is-hot");
    try {
      recognition.start();
    } catch {
      listening = false;
      voiceBtn.classList.remove("is-hot");
    }
  };

  const stopListen = () => {
    if (!listening) return;
    recognition.stop();
  };

  voiceBtn.addEventListener("mousedown", startListen);
  voiceBtn.addEventListener("mouseup", stopListen);
  voiceBtn.addEventListener("mouseleave", stopListen);
  voiceBtn.addEventListener("touchstart", (event) => {
    event.preventDefault();
    startListen();
  });
  voiceBtn.addEventListener("touchend", (event) => {
    event.preventDefault();
    stopListen();
  });
} else {
  voiceBtn.title = "Voice not supported in this browser";
  voiceBtn.addEventListener("click", () => {
    addMessage(
      "system",
      "This browser has no speech recognition. Type instead, or open in Chrome/Edge."
    );
  });
}

function fillClipSelects(selected) {
  if (!clips.length) {
    cameraSelect.innerHTML = `<option value="">No bench clips</option>`;
    cameraSelect.disabled = true;
    return;
  }
  const options = clips
    .map((clip) => {
      const selectedAttr = clip.original_video === selected ? " selected" : "";
      return `<option value="${escapeHtml(clip.original_video)}"${selectedAttr}>${escapeHtml(clip.title)}</option>`;
    })
    .join("");
  cameraSelect.innerHTML = options;
  cameraSelect.disabled = false;
  cameraSelectLive.innerHTML = options;
  cameraSelect.value = selected;
  cameraSelectLive.value = selected;
}

function showFeed() {
  video.classList.add("is-live");
  feedIdle.classList.add("is-hidden");
  liveBar.hidden = false;
}

function applySession(data) {
  clips = data.clips || [];
  const active = clips.find((clip) => clip.id === data.active_id) || clips[0];
  activeVideo = active ? active.original_video : "";
  streamUrl = data.stream_url || "";
  fillClipSelects(activeVideo);
  if (active) feedSource.textContent = active.camera_id || active.title;
  renderSteps(data.steps);
  if (streamUrl) video.src = streamUrl;
}

async function playClip(originalVideo) {
  armCamera.disabled = true;
  armCamera.textContent = "Loading…";
  try {
    const response = await fetch("api/session/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ original_video: originalVideo }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error("select failed");
    lastBucket = -1;
    applySession(data);
    showFeed();
    await video.play();
    addMessage("agent", `Playing ${data.clips.find((clip) => clip.id === data.active_id)?.title || "the bench clip"}.`);
  } catch {
    addMessage("system", "That clip did not start. Pick another bench clip.");
  } finally {
    armCamera.disabled = false;
    armCamera.textContent = "Play clip";
  }
}

armCamera.addEventListener("click", () => {
  const chosen = cameraSelect.value || activeVideo;
  if (!chosen) return;
  playClip(chosen);
});

cameraSelect.addEventListener("change", () => {
  cameraSelectLive.value = cameraSelect.value;
});

cameraSelectLive.addEventListener("change", () => {
  cameraSelect.value = cameraSelectLive.value;
  if (video.classList.contains("is-live")) playClip(cameraSelectLive.value);
});

async function postTick(timeSec) {
  const gen = ++tickGen;
  const videoId = activeVideo;
  try {
    const response = await fetch("api/session/tick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ original_video: videoId, time_sec: timeSec }),
    });
    const data = await response.json();
    if (!response.ok || gen !== tickGen || videoId !== activeVideo) return;
    renderSteps(data.steps);
    for (const alert of data.alerts || []) {
      addMessage("system", alert.text);
      if (alert.speak) speak(alert.text);
    }
    if (data.sim_hint) {
      addMessage("agent", data.sim_hint);
      setSimAdvice(data.sim_hint);
    }
  } catch {
    /* keep the last good step list */
  }
}

function maybeTick(force) {
  if (!activeVideo || !Number.isFinite(video.currentTime)) return;
  const bucket = Math.floor(video.currentTime / 5);
  if (!force && bucket === lastBucket) return;
  lastBucket = bucket;
  postTick(video.currentTime);
}

video.addEventListener("timeupdate", () => maybeTick(false));
video.addEventListener("seeked", () => maybeTick(true));
video.addEventListener("play", () => maybeTick(true));

function tickClock() {
  const now = new Date();
  feedClock.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
}

renderSteps();
tickClock();
setInterval(tickClock, 1000);

addMessage(
  "agent",
  "I am watching an indexed Blink clip. Play it and I will mark a step only after two segments in a row support it."
);

const simAdvice = document.getElementById("simAdvice");
const simStatus = document.getElementById("simStatus");
const simSync = document.getElementById("simSync");
const simRun = document.getElementById("simRun");
const simApply = document.getElementById("simApply");
const wokwiFrame = document.getElementById("wokwiFrame");
const wokwi = new WokwiClient(wokwiFrame);
let lastSim = null;
let nextActionId = "";

function setSimAdvice(text) {
  if (simAdvice && text) simAdvice.textContent = text;
}

function setSimStatus(text) {
  if (simStatus) simStatus.textContent = text;
}

function rememberSim(data) {
  lastSim = data;
  nextActionId = (data.next_actions && data.next_actions[0] && data.next_actions[0].id) || "";
  setSimAdvice(data.advice || "");
  const issues = (data.issues || []).map((item) => item.id).join(", ") || "none";
  setSimStatus(data.ok ? "Sim OK — Blink loop closed" : `Issues: ${issues}`);
}

async function loadSimIntoWokwi(data) {
  rememberSim(data);
  if (!data.files) return;
  try {
    await wokwi.uploadFiles(data.files);
    setSimStatus((simStatus.textContent || "") + " · files uploaded");
  } catch (err) {
    setSimStatus("Wokwi not ready yet — click Run again in a few seconds");
  }
}

simSync.addEventListener("click", async () => {
  setSimStatus("Syncing…");
  try {
    const response = await fetch("api/sim/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ original_video: activeVideo || undefined }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error("sync failed");
    await loadSimIntoWokwi(data);
  } catch {
    setSimStatus("Sync failed");
  }
});

simRun.addEventListener("click", async () => {
  setSimStatus("Starting sim…");
  try {
    let data = lastSim;
    if (!data || !data.files) {
      const response = await fetch("api/sim");
      data = await response.json();
      if (!response.ok) throw new Error("sim failed");
    }
    await loadSimIntoWokwi(data);
    const firmware = (data.embed && data.embed.firmware) || "sketch.ino";
    await wokwi.start(firmware, firmware);
    setSimStatus("Running in Wokwi");
  } catch {
    setSimStatus("Could not start Wokwi — wait for the embed, then try Run");
  }
});

simApply.addEventListener("click", async () => {
  if (!nextActionId) {
    setSimStatus("No next fix — sync first or circuit already OK");
    return;
  }
  setSimStatus(`Applying ${nextActionId}…`);
  try {
    const response = await fetch("api/sim/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action_id: nextActionId,
        original_video: activeVideo || undefined,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error("apply failed");
    await loadSimIntoWokwi(data);
    addMessage("agent", data.advice || "Applied the next sim fix.");
  } catch {
    setSimStatus("Apply failed");
  }
});

fetch("api/session")
  .then((response) => {
    if (!response.ok) throw new Error("session failed");
    return response.json();
  })
  .then((data) => {
    applySession(data);
  })
  .catch(() => {
    addMessage("system", "The bench index did not load. Refresh in a moment.");
  });

fetch("api/sim")
  .then((response) => (response.ok ? response.json() : null))
  .then((data) => {
    if (data) rememberSim(data);
  })
  .catch(() => {});
