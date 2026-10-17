(() => {
  const BASE = (location.pathname === "/app" || location.pathname.startsWith("/app/")) ? "/app" : "";
  const $ = (id) => document.getElementById(id);
  let ws = null, code = "", muted = false, sending = false;

  const modeBadge = $("modeBadge");
  const degradedBadge = $("degradedBadge");

  $("btnMute").onclick = () => {
    muted = !muted;
    $("btnMute").textContent = muted ? "Unmute" : "Mute";
    if (muted) speechSynthesis.cancel();
  };
  $("btnStartCam").onclick = () => startCamera();
  $("btnDemo").onclick = () => startDemoVideo();

  // Auto-start: demo video + scripted verifier so guidance appears immediately
  boot();

  async function boot() {
    const r = await fetch(`${BASE}/api/session`, { method: "POST" });
    code = (await r.json()).code;
    connect(code);
    $("statusLine").textContent = `session ${code} — starting live AI demo`;
    setTimeout(async () => {
      await startDemoVideo();
      // Guaranteed on-screen guidance while Cosmos also analyzes frames
      setTimeout(() => runScriptedGuidance(), 1200);
    }, 500);
  }

  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

  async function runScriptedGuidance() {
    $("pipeLog").textContent += "demo: injecting LED with NO series resistor…\n";
    send({
      type: "verify_demo",
      twin: {
        components: [
          { id: "bat", type: "battery", value: "5" },
          { id: "d1", type: "led", value: "red" },
        ],
        nets: [["bat.pos", "d1.a"], ["d1.k", "bat.neg"]],
        supply_voltage: 5,
      },
    });
    await sleep(6000);
    $("pipeLog").textContent += "demo: fixing with 2200Ω series resistor…\n";
    // allow step-complete / new findings
    send({
      type: "verify_demo",
      twin: {
        components: [
          { id: "bat", type: "battery", value: "5" },
          { id: "r1", type: "resistor", value: "2200" },
          { id: "d1", type: "led", value: "red" },
        ],
        nets: [["bat.pos", "r1.a"], ["r1.b", "d1.a"], ["d1.k", "bat.neg"]],
        supply_voltage: 5,
      },
    });
  }

  function connect(c) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    // single role "phone" still sends frames; we also receive twin/guidance on same socket
    ws = new WebSocket(`${proto}://${location.host}${BASE}/ws?code=${c}&role=phone`);
    ws.onopen = () => { modeBadge.textContent = `live ${c}`; };
    ws.onmessage = (ev) => onMsg(JSON.parse(ev.data));
    ws.onerror = () => { modeBadge.textContent = "ws error"; };
    ws.onclose = () => { modeBadge.textContent = "ws closed"; };
  }

  function send(obj) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
  }

  function onMsg(msg) {
    if (msg.type === "joined") modeBadge.textContent = `live ${msg.code}`;
    if (msg.degraded) degradedBadge.classList.remove("hidden");
    if (msg.type === "frame_preview" && msg.jpeg_b64) {
      // optional; video element already shows local feed
    }
    if (msg.type === "twin") {
      renderTwin(msg);
      $("twinOut").textContent = JSON.stringify(msg.twin, null, 2).slice(0, 2000);
      $("pipeLog").textContent += `twin ok badge=${(msg.verification||{}).badge} findings=${(msg.findings||[]).length}\n`;
    }
    if (msg.type === "guidance") showGuidance(msg);
    if (msg.type === "perception_error") {
      $("pipeLog").textContent += `cosmos error ${JSON.stringify(msg.meta)}\n`;
      $("caption").textContent = "Perception failed — retrying…";
    }
    if (msg.type === "status") {
      $("pipeLog").textContent += `status ${msg.reason || ""}\n`;
    }
    if (msg.timing) renderTiming(msg.timing);
  }

  function showGuidance(msg) {
    $("caption").textContent = msg.text || "";
    $("guidanceLog").textContent += `[${(msg.finding_ids || []).join(",")}] ${msg.text}\n`;
    $("statusLine").textContent = "guidance received";
    if (!muted && msg.text) {
      const u = new SpeechSynthesisUtterance(msg.text);
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    }
  }

  function renderTwin(msg) {
    const badge = $("verifyBadge");
    const b = (msg.verification && msg.verification.badge) || "simulation-verified";
    badge.textContent = b;
    badge.className = "badge " + (b === "formally verified" ? "formal" : "sim");
    const findings = msg.findings || [];
    $("findings").innerHTML = findings.length
      ? findings.map((f) => `<div class="finding ${f.severity}"><strong>${f.rule}</strong> — ${f.message}</div>`).join("")
      : '<div class="muted">No findings</div>';
    const z = msg.verification && msg.verification.z3;
    if (z && z.counterexample_v != null) {
      $("z3Box").textContent = `Z3 counterexample V=${z.counterexample_v} V (simulation-verified)`;
    } else if (z && z.proved) {
      $("z3Box").textContent = "Z3 invariant proved across V∈[3,12] — formally verified";
    } else {
      $("z3Box").textContent = "";
    }
    drawGraph(msg.twin || {}, findings);
  }

  function renderTiming(t) {
    const stages = [
      ["yolo", t.yolo_ms || 0],
      ["cosmos", t.cosmos_ms || 0],
      ["verify", t.verify_ms || 0],
      ["speak", t.speak_ms || 0],
    ];
    const total = stages.reduce((a, [, v]) => a + (Number(v) || 0), 0);
    $("bars").innerHTML = stages.map(([n, v]) => {
      const pct = Math.min(100, (Number(v) || 0) / 40);
      return `<div class="bar-row"><span>${n}</span><i style="width:${pct}%"></i><span>${Math.round(v || 0)}ms</span></div>`;
    }).join("");
    $("budgetFill").style.width = `${Math.min(100, (total / 4000) * 100)}%`;
  }

  function drawGraph(twin, findings) {
    const svg = $("graph");
    const comps = twin.components || [];
    const nets = twin.nets || [];
    const bad = new Set();
    for (const f of findings || []) {
      const ev = f.evidence || {};
      if (ev.led) bad.add(ev.led);
      if (ev.component) bad.add(ev.component);
      if (ev.resistor) bad.add(ev.resistor);
    }
    const W = 640, H = 280;
    const nodes = comps.map((c, i) => {
      const ang = (i / Math.max(comps.length, 1)) * Math.PI * 2 - Math.PI / 2;
      const r = 90;
      return { id: c.id, type: c.type, x: W / 2 + Math.cos(ang) * r, y: H / 2 + Math.sin(ang) * r, bad: bad.has(c.id) };
    });
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    let edges = "";
    for (const net of nets) {
      const ids = [...new Set(net.map((e) => String(e).split(".")[0]))].filter((id) => byId[id]);
      for (let i = 0; i < ids.length - 1; i++) {
        const a = byId[ids[i]], b = byId[ids[i + 1]];
        edges += `<line class="edge${(a.bad || b.bad) ? " bad" : ""}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`;
      }
    }
    const circles = nodes.map((n) =>
      `<g><circle class="node${n.bad ? " bad" : ""}" cx="${n.x}" cy="${n.y}" r="22"/><text x="${n.x}" y="${n.y + 4}" text-anchor="middle" fill="#e8f2ec" font-size="10" font-family="IBM Plex Mono, monospace">${n.id}</text></g>`
    ).join("");
    svg.innerHTML = edges + circles;
  }

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
        audio: false,
      });
      const video = $("video");
      video.srcObject = stream;
      await video.play();
      $("statusLine").textContent = "camera ok — sending frames";
      startFrameLoop(video);
    } catch (err) {
      $("statusLine").textContent = "camera failed: " + err.name;
      $("caption").textContent = "Camera blocked — using demo video instead";
      startDemoVideo();
    }
  }

  async function startDemoVideo() {
    $("statusLine").textContent = "loading demo breadboard clip…";
    // Server-hosted looping demo mp4
    const video = $("video");
    video.srcObject = null;
    video.src = `${BASE}/static/demo_breadboard.mp4`;
    video.loop = true;
    try {
      await video.play();
    } catch (_) {
      // autoplay may need mute (already muted)
    }
    $("statusLine").textContent = "demo video playing — AI analyzing…";
    startFrameLoop(video);
  }

  function startFrameLoop(video) {
    if (sending) return;
    sending = true;
    const canvas = document.createElement("canvas");
    setInterval(() => {
      if (!video.videoWidth) return;
      const w = 640;
      const h = Math.round(video.videoHeight * (w / video.videoWidth)) || 360;
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(video, 0, 0, w, h);
      canvas.toBlob(async (blob) => {
        if (!blob) return;
        const buf = await blob.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let s = "", chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk)
          s += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        send({ type: "frame", jpeg_b64: btoa(s) });
      }, "image/jpeg", 0.72);
    }, 1000);
  }
})();
