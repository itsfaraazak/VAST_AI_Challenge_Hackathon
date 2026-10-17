/**
 * Wokwi Blink panel — official embed protocol + hexi AVR compile.
 */
import { MessagePortTransport } from "./message-port-transport.js";
import { WokwiClient } from "./wokwi-client.js";
import { detectAvrBoard, buildArduinoHex } from "./build.js";

export function mountSimPanel({ onAdvice } = {}) {
  const adviceEl = document.getElementById("simAdvice");
  const statusEl = document.getElementById("simStatus");
  const syncBtn = document.getElementById("simSync");
  const runBtn = document.getElementById("simRun");
  const applyBtn = document.getElementById("simApply");
  const frame = document.getElementById("wokwiFrame");
  const serialEl = document.getElementById("simSerial");

  if (!frame || !syncBtn || !runBtn || !applyBtn) {
    return { remember() {}, setAdvice() {} };
  }

  let wokwi = null;
  let wokwiReady = false;
  let lastSim = null;
  let nextActionId = "";
  let connecting = false;

  function setAdvice(text) {
    if (adviceEl && text) adviceEl.textContent = text;
    if (typeof onAdvice === "function" && text) onAdvice(text);
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function remember(data) {
    if (!data) return;
    lastSim = data;
    nextActionId =
      (data.next_actions && data.next_actions[0] && data.next_actions[0].id) || "";
    setAdvice(data.advice || "");
    const issues = (data.issues || []).map((i) => i.id).join(", ") || "none";
    setStatus(data.ok ? "Sim OK — Blink loop closed" : `Issues: ${issues}`);
  }

  window.addEventListener("message", (event) => {
    if (!event.data || !event.data.port) return;
    if (event.source !== frame.contentWindow) return;
    if (wokwi) return;

    wokwi = new WokwiClient(new MessagePortTransport(event.data.port));
    wokwi.addEventListener("wokwi:connected", async () => {
      wokwiReady = true;
      setStatus("Wokwi ready");
      try {
        await wokwi.serialMonitorListen();
      } catch {
        /* optional */
      }
    });
    wokwi.addEventListener("serial-monitor:data", (ev) => {
      if (!serialEl) return;
      const bytes = new Uint8Array(ev.detail.bytes || []);
      serialEl.textContent += new TextDecoder().decode(bytes);
      serialEl.scrollTop = serialEl.scrollHeight;
    });
  });

  async function fetchSim(path, body) {
    const opts = body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {};
    const response = await fetch(path, opts);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "sim request failed");
    return data;
  }

  async function runInWokwi(data) {
    remember(data);
    if (!data.files) throw new Error("No sim files");

    if (!wokwiReady || !wokwi) {
      // Nudge the iframe to reconnect if needed
      if (!connecting) {
        connecting = true;
        frame.src = "https://wokwi.com/experimental/embed";
        connecting = false;
      }
      throw new Error("Wokwi still loading — click Run again in a few seconds");
    }

    const files = { ...data.files };
    const diagram = files["diagram.json"];
    const board = diagram ? detectAvrBoard(diagram) : null;

    if (board && files["sketch.ino"] && !files["sketch.hex"]) {
      setStatus(`Compiling for ${board}…`);
      const out = await buildArduinoHex(files["sketch.ino"], board);
      files["sketch.hex"] = out.hex;
    }

    const start = files["sketch.hex"]
      ? { firmware: "sketch.hex", elf: "sketch.hex" }
      : { firmware: "sketch.ino", elf: "sketch.ino" };

    setStatus("Uploading to Wokwi…");
    try {
      await wokwi.simPause();
    } catch {
      /* first run */
    }
    for (const [name, content] of Object.entries(files)) {
      await wokwi.fileUpload(name, typeof content === "string" ? content : JSON.stringify(content));
    }
    setStatus("Starting…");
    if (serialEl) serialEl.textContent = "";
    await wokwi.simStart(start);
    setStatus("Running in Wokwi");
  }

  syncBtn.addEventListener("click", async () => {
    setStatus("Syncing from bench…");
    try {
      const data = await fetchSim("api/sim/sync", {});
      remember(data);
      setStatus((statusEl.textContent || "Synced") + " — press Run");
    } catch (err) {
      setStatus(`Sync failed: ${err.message || err}`);
    }
  });

  runBtn.addEventListener("click", async () => {
    setStatus("Starting sim…");
    try {
      let data = lastSim;
      if (!data || !data.files) {
        data = await fetchSim("api/sim");
      }
      await runInWokwi(data);
    } catch (err) {
      setStatus(String(err.message || err));
    }
  });

  applyBtn.addEventListener("click", async () => {
    if (!nextActionId) {
      setStatus("No next fix — sync first or circuit already OK");
      return;
    }
    setStatus(`Applying ${nextActionId}…`);
    try {
      const data = await fetchSim("api/sim/apply", { action_id: nextActionId });
      remember(data);
      try {
        await runInWokwi(data);
      } catch (err) {
        setStatus(`Applied, but Wokwi: ${err.message || err}`);
      }
    } catch (err) {
      setStatus(`Apply failed: ${err.message || err}`);
    }
  });

  // Prefetch advice so the status line is useful before Run.
  fetchSim("api/sim")
    .then(remember)
    .catch(() => setStatus("Sim idle — Sync from bench when ready"));

  return { remember, setAdvice };
}
