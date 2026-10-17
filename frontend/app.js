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

let mediaStream = null;
let videoDevices = [];
let preferredDeviceId = "";
let frameBusy = false;
let chatBusy = false;
let frameTimer = null;
let lastAdvice = "";
const canvas = document.createElement("canvas");

function renderSteps(steps) {
  const rows =
    steps && steps.length
      ? steps
      : STEPS.map((step, i) => ({
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
  body.innerHTML = String(text);
  el.append(whoEl, body);
  thread.appendChild(el);
  thread.scrollTop = thread.scrollHeight;
}

function speak(text) {
  if (!window.speechSynthesis || !text) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.05;
  window.speechSynthesis.speak(utterance);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || chatBusy) return;
  addMessage("user", escapeHtml(text));
  input.value = "";
  autoGrow();
  chatBusy = true;
  try {
    const response = await fetch("api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "chat failed");
    addMessage("agent", escapeHtml(data.answer || ""));
  } catch {
    addMessage("system", "Chat did not come back. Is the backend running?");
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

/* Voice */
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

/* Camera */

function deviceScore(label = "") {
  const l = label.toLowerCase();
  if (l.includes("desk view")) return 100;
  if (l.includes("continuity")) return 90;
  if (l.includes("iphone") || l.includes("ipad")) return 80;
  if (l.includes("back") || l.includes("rear") || l.includes("environment"))
    return 50;
  if (l.includes("facetime") || l.includes("integrated") || l.includes("built-in"))
    return 20;
  return 10;
}

function friendlyLabel(device, index) {
  const raw = (device.label || "").trim();
  if (!raw) return `Camera ${index + 1}`;
  if (/desk view/i.test(raw)) return `Desk View — ${raw}`;
  if (/continuity/i.test(raw)) return `Continuity — ${raw}`;
  return raw;
}

function pickPreferredId(devices) {
  if (!devices.length) return "";
  const ranked = [...devices].sort(
    (a, b) => deviceScore(b.label) - deviceScore(a.label)
  );
  return ranked[0].deviceId;
}

function fillCameraSelects(selectedId) {
  const options = videoDevices
    .map((d, i) => {
      const id = d.deviceId;
      const label = friendlyLabel(d, i);
      const sel = id === selectedId ? " selected" : "";
      return `<option value="${id}"${sel}>${label}</option>`;
    })
    .join("");

  if (!videoDevices.length) {
    cameraSelect.innerHTML = `<option value="">No cameras found</option>`;
    cameraSelect.disabled = true;
    return;
  }

  cameraSelect.innerHTML = options;
  cameraSelect.disabled = false;
  cameraSelectLive.innerHTML = options;
  if (selectedId) {
    cameraSelect.value = selectedId;
    cameraSelectLive.value = selectedId;
  }
}

async function listCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) {
    cameraSelect.innerHTML = `<option value="">Camera API unavailable</option>`;
    return [];
  }
  const all = await navigator.mediaDevices.enumerateDevices();
  videoDevices = all.filter((d) => d.kind === "videoinput");
  preferredDeviceId = pickPreferredId(videoDevices);
  fillCameraSelects(preferredDeviceId || videoDevices[0]?.deviceId || "");
  return videoDevices;
}

function stopStream() {
  if (frameTimer) {
    clearInterval(frameTimer);
    frameTimer = null;
  }
  if (!mediaStream) return;
  for (const track of mediaStream.getTracks()) track.stop();
  mediaStream = null;
}

function grabJpegB64() {
  if (!video.videoWidth) return "";
  const maxW = 640;
  const scale = Math.min(1, maxW / video.videoWidth);
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
  return dataUrl.split(",", 2)[1] || "";
}

async function pushFrame() {
  if (frameBusy || !mediaStream) return;
  const image = grabJpegB64();
  if (!image) return;
  frameBusy = true;
  try {
    const response = await fetch("api/frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_jpeg_b64: image }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "frame failed");
    renderSteps(data.steps);
    for (const alert of data.alerts || []) {
      addMessage("system", escapeHtml(alert.text || ""));
      if (alert.speak) speak(alert.text || "");
    }
    if (data.advice && data.advice !== lastAdvice) {
      lastAdvice = data.advice;
      addMessage("agent", escapeHtml(data.advice));
    }
  } catch {
    /* keep UI responsive if Cosmos is slow/down */
  } finally {
    frameBusy = false;
  }
}

function startFrameLoop() {
  if (frameTimer) clearInterval(frameTimer);
  // first look quickly, then every 5s
  setTimeout(() => pushFrame(), 800);
  frameTimer = setInterval(() => pushFrame(), 5000);
}

async function startCamera(deviceId) {
  const constraints = {
    audio: false,
    video: deviceId
      ? {
          deviceId: { exact: deviceId },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        }
      : {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
  };

  stopStream();
  mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
  video.srcObject = mediaStream;
  await video.play().catch(() => {});
  video.classList.add("is-live");
  feedIdle.classList.add("is-hidden");
  liveBar.hidden = false;

  const track = mediaStream.getVideoTracks()[0];
  const label = track?.label || "camera";
  feedSource.textContent = label;
  preferredDeviceId =
    track?.getSettings?.().deviceId || deviceId || preferredDeviceId;

  await listCameras();
  fillCameraSelects(preferredDeviceId);
  startFrameLoop();
  return label;
}

armCamera.addEventListener("click", async () => {
  armCamera.disabled = true;
  armCamera.textContent = "Arming…";
  try {
    if (!videoDevices.some((d) => d.label)) {
      const probe = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
      for (const t of probe.getTracks()) t.stop();
      await listCameras();
    }

    const chosen =
      cameraSelect.value || preferredDeviceId || videoDevices[0]?.deviceId || "";
    const label = await startCamera(chosen);
    addMessage(
      "agent",
      `Camera armed on <strong>${escapeHtml(label)}</strong>. Sending stills to Cosmos — Desk View is best for the breadboard.`
    );
  } catch (err) {
    const name = err?.name || "Error";
    addMessage(
      "system",
      name === "NotAllowedError"
        ? "Camera permission blocked. Allow it in the browser, then arm again."
        : "Could not open that camera. Enable Continuity / Desk View, then pick it from the list."
    );
  } finally {
    armCamera.disabled = false;
    armCamera.textContent = "Arm camera";
  }
});

async function onCameraChange(selectEl) {
  const id = selectEl.value;
  if (!id) return;
  try {
    const label = await startCamera(id);
    addMessage("agent", `Switched feed to <strong>${escapeHtml(label)}</strong>.`);
  } catch {
    addMessage("system", "That camera failed to open. Try another source.");
  }
}

cameraSelect.addEventListener("change", () => {
  preferredDeviceId = cameraSelect.value;
});
cameraSelectLive.addEventListener("change", () =>
  onCameraChange(cameraSelectLive)
);

if (navigator.mediaDevices?.addEventListener) {
  navigator.mediaDevices.addEventListener("devicechange", () => {
    listCameras();
  });
}

listCameras().catch(() => {
  cameraSelect.innerHTML = `<option value="">Allow camera to list devices</option>`;
});

function tickClock() {
  const now = new Date();
  feedClock.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
}

renderSteps();
tickClock();
setInterval(tickClock, 1000);

fetch("api/session")
  .then((response) => (response.ok ? response.json() : null))
  .then((data) => {
    if (data?.steps) renderSteps(data.steps);
  })
  .catch(() => {});

addMessage(
  "agent",
  "Live mode: your camera is the source. Cosmos watches stills; VAST Arduino clips only teach better placement tips. Arm the camera to start."
);
