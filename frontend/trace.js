// CURRENT "behind the scenes" telemetry panel. window.CurrentTrace = {mount, push, setServices, clear}
const STAGES = ["frame", "yolo", "gate", "cosmos", "verify", "coach"];
const NODE_LABEL = { frame: "FRAME", yolo: "YOLO", gate: "GATE", cosmos: "COSMOS", verify: "VERIFY", coach: "COACH" };
const SPARK_STAGES = ["yolo", "cosmos", "verify", "coach", "asr"];
const SPONSOR_NAME = { nvidia: "NVIDIA", coreweave: "CoreWeave GPU", wandb: "W&B", vast: "VAST", cursor: "Cursor", local: "local" };
const SVC = { cosmos3_reason: "Cosmos3", yolo11: "YOLO11", cosmos_embed1: "Embed", canary_1b: "Canary", wandb_inference: "W&B LLM", vss_retrieval: "VAST" };
const MAX_ROWS = 120;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = { root: null, rows: new Map(), counts: {}, lat: {}, nodes: {}, state: {}, el: {} };

function mount(host) {
  const r = document.createElement("div");
  r.className = "ct-root";
  r.innerHTML = `<div class="ct-head"><span class="ct-live"></span><span class="ct-title">BEHIND THE SCENES</span><span class="ct-caret">▾</span></div>
  <div class="ct-body">
   <div class="ct-pipe"></div>
   <div class="ct-spark"></div>
   <div class="ct-counts"></div>
   <div class="ct-svc"></div>
   <div class="ct-log"></div></div>`;
  host.appendChild(r);
  S.root = r;
  S.el = { pipe: r.querySelector(".ct-pipe"), spark: r.querySelector(".ct-spark"), counts: r.querySelector(".ct-counts"), svc: r.querySelector(".ct-svc"), log: r.querySelector(".ct-log") };
  r.querySelector(".ct-head").onclick = () => r.classList.toggle("ct-collapsed");
  S.el.pipe.innerHTML = STAGES.map((s) => `<div class="ct-node" data-s="${s}">${NODE_LABEL[s]}</div>`).join('<span class="ct-arrow">▸</span>');
  STAGES.forEach((s) => (S.nodes[s] = S.el.pipe.querySelector(`[data-s=${s}]`)));
  S.el.spark.innerHTML = SPARK_STAGES.map((s) => `<div class="ct-sp" data-s="${s}"><b>${s}</b><svg viewBox="0 0 60 16" preserveAspectRatio="none"><polyline fill="none" stroke="#38f0ff" stroke-width="1.2"/></svg><i>--</i></div>`).join("");
  renderCounts();
}

function setNode(stage, status) {
  const n = S.nodes[stage];
  if (!n) return;
  n.classList.remove("ct-on", "ct-done", "ct-err", "ct-skip");
  n.classList.add({ start: "ct-on", ok: "ct-done", error: "ct-err", skip: "ct-skip" }[status] || "ct-done");
}

function spark(stage, ms) {
  const a = (S.lat[stage] = S.lat[stage] || []);
  a.push(ms);
  if (a.length > 24) a.shift();
  const box = S.el.spark?.querySelector(`[data-s=${stage}]`);
  if (!box) return;
  const max = Math.max(...a, 1);
  const pts = a.map((v, i) => `${a.length < 2 ? 0 : (i / (a.length - 1)) * 60},${15 - (v / max) * 14}`).join(" ");
  box.querySelector("polyline").setAttribute("points", a.length < 2 ? "0,8 60,8" : pts);
  box.querySelector("i").textContent = Math.round(ms) + "ms";
}

function renderCounts() {
  const c = S.counts;
  const parts = Object.keys(c).sort((a, b) => c[b] - c[a]).map((k) => `${SPONSOR_NAME[k] || k} ${c[k]}`);
  S.el.counts.textContent = parts.length ? parts.join(" · ") : "no calls yet";
}

function rowHTML(m) {
  const ms = m.ms != null ? Math.round(m.ms) + " ms" : m.status === "start" ? "…" : "";
  return `<span class="ct-dot"></span><div class="ct-main"><span class="ct-lbl">${esc(m.label || m.stage)}</span><span class="ct-badge ct-b-${esc(m.sponsor)}">${esc(SPONSOR_NAME[m.sponsor] || m.sponsor)}</span>${m.model ? ` <span class="ct-mdl">${esc(m.model)}</span>` : ""}</div><span class="ct-ms">${ms}</span>${m.detail ? `<div class="ct-det">${esc(m.detail)}</div>` : ""}`;
}

function push(m) {
  if (!S.root || !m) return;
  if (m.type && m.type !== "trace") return;
  const stage = m.stage;
  setNode(stage, m.status);
  if (m.status === "start" || m.status === "skip" || (m.status !== "start" && !S.rows.has(m.id))) {
    // count each call once (at start, or at its single event if no start was seen)
    if (m.sponsor && m.status !== "skip") {
      S.counts[m.sponsor] = (S.counts[m.sponsor] || 0) + 1;
      if (m.sponsor === "nvidia" && (stage === "yolo" || stage === "cosmos")) {
        /* GPU hosted on CoreWeave */
        if (stage === "yolo" || stage === "cosmos") S.counts.coreweave = (S.counts.coreweave || 0) + 1;
      }
      renderCounts();
    }
  }
  if (m.ms != null && m.status !== "start") spark(stage, m.ms);
  let row = S.rows.get(m.id);
  const stick = S.el.log.scrollTop + S.el.log.clientHeight >= S.el.log.scrollHeight - 20;
  if (!row) {
    row = document.createElement("div");
    S.rows.set(m.id, row);
    S.el.log.appendChild(row);
    while (S.el.log.children.length > MAX_ROWS) {
      const f = S.el.log.firstChild;
      for (const [k, v] of S.rows) if (v === f) { S.rows.delete(k); break; }
      f.remove();
    }
  }
  row.className = `ct-row ct-${m.status}`;
  row.innerHTML = rowHTML(m);
  if (stick) S.el.log.scrollTop = S.el.log.scrollHeight;
}

function setServices(h) {
  if (!S.root) return;
  const svc = (h && h.services) || h || {};
  S.el.svc.innerHTML = Object.keys(SVC).filter((k) => k in svc).map((k) => `<span class="ct-chip ${svc[k] ? "ct-up" : "ct-down"}">${SVC[k]}</span>`).join("");
}

function clear() {
  if (!S.root) return;
  S.rows.clear(); S.counts = {}; S.lat = {};
  S.el.log.innerHTML = "";
  Object.values(S.nodes).forEach((n) => n.classList.remove("ct-on", "ct-done", "ct-err", "ct-skip"));
  S.el.spark.querySelectorAll(".ct-sp").forEach((b) => { b.querySelector("polyline").removeAttribute("points"); b.querySelector("i").textContent = "--"; });
  renderCounts();
}

const api = { mount, push, setServices, clear };
window.CurrentTrace = api;
export default api;
export { mount, push, setServices, clear };
