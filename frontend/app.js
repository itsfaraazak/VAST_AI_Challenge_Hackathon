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

let activeStep = 0;
let mediaStream = null;

function renderSteps() {
  stepTotal.textContent = String(STEPS.length);
  stepProgress.textContent = String(Math.min(activeStep + 1, STEPS.length));
  stepList.innerHTML = STEPS.map((step, i) => {
    const state =
      i < activeStep ? "is-done" : i === activeStep ? "is-active" : "";
    return `
      <li class="step ${state}" data-id="${step.id}">
        <span class="step__index">${String(i + 1).padStart(2, "0")}</span>
        <p class="step__title">${step.title}</p>
        <p class="step__hint">${step.hint}</p>
      </li>
    `;
  }).join("");
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

function agentReply(userText) {
  const lower = userText.toLowerCase();
  const step = STEPS[activeStep];

  if (/next|done|finished|complete|tick/.test(lower) && activeStep < STEPS.length) {
    activeStep = Math.min(activeStep + 1, STEPS.length);
    renderSteps();
    if (activeStep >= STEPS.length) {
      return "Sequence complete. Blink should be breathing. Ask me what you changed if it dies later.";
    }
    return `Locked step ${activeStep}. Next up: <strong>${STEPS[activeStep].title}</strong>.`;
  }

  if (/resistor|fry|burn|short/.test(lower)) {
    return "If that LED has no resistor on the way to 5V, stop. Unplug USB, then finish step 02.";
  }

  if (/pin|wrong|d13|13|12|8|9/.test(lower)) {
    return `Your sketch is almost certainly driving <strong>D13</strong>. If the wire landed on another header, that is why the LED ignores you. Re-check step 03 against the code.`;
  }

  if (/what.*(change|differ|move)|earlier|before|memory/.test(lower)) {
    return "I keep a timeline of every stable board state. Once the pipeline is wired in, I will replay the clip where the red jumper moved.";
  }

  if (/why|not work|broken|help/.test(lower)) {
    return `On <strong>${step.title}</strong>: ${step.hint} Show me a closer angle of the header if the pins look ambiguous.`;
  }

  return `Still on step ${String(activeStep + 1).padStart(2, "0")} — ${step.title}. Say “next” when that connection is solid, or tell me what looks wrong.`;
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", escapeHtml(text));
  input.value = "";
  autoGrow();
  window.setTimeout(() => {
    addMessage("agent", agentReply(text));
  }, 280);
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

function escapeHtml(str) {
  return str
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
  voiceBtn.addEventListener("touchstart", (e) => {
    e.preventDefault();
    startListen();
  });
  voiceBtn.addEventListener("touchend", (e) => {
    e.preventDefault();
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
armCamera.addEventListener("click", async () => {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    video.srcObject = mediaStream;
    video.classList.add("is-live");
    feedIdle.classList.add("is-hidden");
    addMessage("agent", "Camera armed. Build step 01 when you are ready.");
  } catch {
    addMessage(
      "system",
      "Could not open the camera. Allow permission, or use HTTPS / localhost."
    );
  }
});

function tickClock() {
  const now = new Date();
  feedClock.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
}

/* Demo: click a done step to jump (handy while wiring UI) */
stepList.addEventListener("click", (e) => {
  const li = e.target.closest(".step");
  if (!li) return;
  const idx = [...stepList.children].indexOf(li);
  if (idx < 0) return;
  activeStep = idx;
  renderSteps();
});

renderSteps();
tickClock();
setInterval(tickClock, 1000);

addMessage(
  "agent",
  "I am watching the bench for <strong>Blink</strong>. Arm the camera, then work the sequence on the right. I will interrupt if you skip the resistor."
);
