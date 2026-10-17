/**
 * CURRENT - holographic 3D circuit preview (three.js r160, ES module, no build step).
 *
 * Host page should include (before this module loads) an import map:
 *   <script type="importmap">{"imports":{
 *     "three":"https://unpkg.com/three@0.160.0/build/three.module.js",
 *     "three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script>
 * If no import map is present we fall back to esm.sh URLs automatically.
 *
 * API (window.CurrentScene and ES exports):
 *   mount(hostEl)  update(state)  setBoard('nano'|'esp32')  flash('ok'|'error')
 *   state = { board, project:{steps:[{id,title,pins,wires:[{from,to,color}],parts}]}, stepIndex,
 *             twin:{components,nets,placements,observation}|null, findings:[{id,severity,message,parts,pins}] }
 * Layer 1 TARGET = cyan wireframe ghost.  Layer 2 OBSERVED = solid parts from the twin
 * (red + halo + label when wrong, amber for warnings, green shimmer when the step is satisfied).
 */

let THREE = null, OrbitControls, EffectComposer, RenderPass, UnrealBloomPass, OutputPass;

async function loadLibs() {
  try {
    THREE = await import("three");
    OrbitControls = (await import("three/addons/controls/OrbitControls.js")).OrbitControls;
    EffectComposer = (await import("three/addons/postprocessing/EffectComposer.js")).EffectComposer;
    RenderPass = (await import("three/addons/postprocessing/RenderPass.js")).RenderPass;
    UnrealBloomPass = (await import("three/addons/postprocessing/UnrealBloomPass.js")).UnrealBloomPass;
    OutputPass = (await import("three/addons/postprocessing/OutputPass.js")).OutputPass;
  } catch (e) {
    const B = "https://esm.sh/three@0.160.0";
    THREE = await import(B);
    const J = B + "/examples/jsm/";
    OrbitControls = (await import(J + "controls/OrbitControls.js")).OrbitControls;
    try {
      EffectComposer = (await import(J + "postprocessing/EffectComposer.js")).EffectComposer;
      RenderPass = (await import(J + "postprocessing/RenderPass.js")).RenderPass;
      UnrealBloomPass = (await import(J + "postprocessing/UnrealBloomPass.js")).UnrealBloomPass;
      OutputPass = (await import(J + "postprocessing/OutputPass.js")).OutputPass;
    } catch (e2) { EffectComposer = null; }
  }
}

/* ---------- constants & data ---------- */
const C = { cyan: 0x19e3ff, mag: 0xff3ad8, green: 0x3dff8f, red: 0xff2d55, amber: 0xffb21e, white: 0xd8f4ff, bg: 0x03060d };
const WIRE_COL = { red: 0xff3b3b, black: 0x4a5a6c, blue: 0x2f7bff, green: 0x31d46b, yellow: 0xffe03a, orange: 0xff8a1f, white: 0xe8f0ff, purple: 0xa855f7, brown: 0x9b6a3b, grey: 0x9aa5b1, gray: 0x9aa5b1 };
const ROWS = "ABCDEFGHIJ";
const BOARDS = {
  nano: {
    label: "ARDUINO NANO", cz: 0, half: 1.5, sig: "D13", gnd: "GND_R",
    right: ["VIN", "GND_R", "RST_R", "5V", "A7", "A6", "A5", "A4", "A3", "A2", "A1", "A0", "AREF", "3V3", "D13"],
    left: ["D1", "D0", "RST_L", "GND_L", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12"],
  },
  esp32: {
    label: "ESP32 DEVKIT", cz: 0, half: 5.5, sig: "D2", gnd: "GND_R",
    right: ["D23", "D22", "TX0", "RX0", "D21", "D19", "D18", "D5", "TX2", "RX2", "D4", "D2", "D15", "GND_R", "3V3"],
    left: ["EN", "VP", "VN", "D34", "D35", "D32", "D33", "D25", "D26", "D27", "D14", "D12", "D13", "GND_L", "VIN"],
  },
};

let V3 = null; // THREE.Vector3 ctor shortcut after load
const TABLE = {}; // board -> Map(name -> Vector3 pin top)
const norm = (s) => String(s == null ? "" : s).trim().toUpperCase();
const arr = (a) => (Array.isArray(a) ? a : []);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

function pinTable(key) {
  const B = BOARDS[key], m = new Map();
  [["right", -1], ["left", 1]].forEach(([side, sgn]) => {
    B[side].forEach((n, i) => m.set(n, new V3(i - 6.5, 1.0, B.cz + sgn * B.half)));
  });
  return m;
}
function resolvePin(board, raw) {
  const B = BOARDS[board], T = TABLE[board];
  if (!B || !T) return null;
  let k = norm(raw).replace(/[\s-]/g, "");
  if (k === "GND") k = B.gnd;
  const g = /^GPIO(\d+)$/.exec(k);
  if (g) k = "D" + g[1];
  if (k === "+5V" || k === "VBUS") k = "5V";
  if (k === "5V" && !T.has(k) && T.has("VIN")) k = "VIN";
  return T.has(k) ? { name: k, pos: T.get(k).clone() } : null;
}
function holePos(col, row) {
  const i = ROWS.indexOf(String(row).toUpperCase());
  if (i < 0 || !(col >= 1 && col <= 30)) return null;
  return new V3(col - 15.5, 0, i < 5 ? -5.5 + i : 1.5 + (i - 5));
}
function parseHole(s) {
  const m = /^\s*([A-Ja-j])\s*(\d{1,2})\s*$/.exec(String(s || ""));
  return m && holePos(+m[2], m[1]) ? { col: +m[2], row: m[1].toUpperCase() } : null;
}
function defaultLayout(board) {
  const B = BOARDS[board], sig = resolvePin(board, B.sig).pos, gnd = resolvePin(board, B.gnd).pos;
  const c0 = clamp(Math.round(sig.x + 15.5), 3, 24);
  return {
    c0, sig, gnd,
    // board straddles the centre channel, so its pins sit in holes E/F (or A/J): parts share the pin's strip
    sigHole: holePos(c0, "D"),
    r: { a: holePos(c0, "C"), b: holePos(c0 + 4, "C") },
    led: { a: holePos(c0 + 4, "B"), k: holePos(c0 + 5, "B") },
    gndHole: holePos(c0 + 5, "D"),
    rail: new V3(c0 + 5 - 15.5, 0, 7.3),
    railPin: new V3(gnd.x, 0, 7.3),
  };
}
const slotOf = (id, t, kind) => {
  t = String(t).toLowerCase();
  if (kind === "led") return /^(a|anode|\+|pos|long)/.test(t) ? "a" : "k";
  return /^(a|1|p1|in)$/.test(t) ? "a" : "b";
};
const isPinNode = (k) => /^(D\d+|A\d+|5V|3V3|VIN|GND|EN|TX\d?|RX\d?|VP|VN|RST|AREF)$/.test(k);
const nodeKey = (s) => {
  let k = norm(s);
  if (/^GND/.test(k)) return "GND";
  const g = /^GPIO(\d+)$/.exec(k);
  if (g) k = "D" + g[1];
  if (k === "+5V" || k === "VBUS") k = "5V";
  return k;
};
const kindOf = (c) => { const k = partKindOf(c && c.type) || partKindOf(c && c.id); return k || "other"; };
const matches = (fid, c) => {
  const f = norm(fid), id = norm(c.id), ty = norm(c.type);
  return f === id || f === ty || (f === "LED" && kindOf(c) === "led") || (/^RES/.test(f) && kindOf(c) === "resistor") || (f === "R" + (c.value || "") && kindOf(c) === "resistor");
};

/* ---------- electrical analysis (client-side, mirrors verifier intent) ---------- */
function analyze(st) {
  const out = { hints: {}, parts: {}, complete: false, stepOk: false, badPins: new Set(), loose: [], uf: null };
  const tw = st.twin;
  if (!tw || !Array.isArray(tw.components)) return out;
  const comps = tw.components.filter((c) => c && c.id != null);
  const nets = arr(tw.nets).filter(Array.isArray);
  const par = new Map();
  const find = (x) => { if (!par.has(x)) par.set(x, x); while (par.get(x) !== x) { par.set(x, par.get(par.get(x))); x = par.get(x); } return x; };
  const uni = (a, b) => par.set(find(a), find(b));
  nets.forEach((n) => { const ks = n.map(nodeKey); ks.forEach((k) => find(k)); ks.slice(1).forEach((k) => uni(ks[0], k)); });
  const terms = (c) => [...par.keys()].filter((k) => k.startsWith(norm(c.id) + "."));
  comps.filter((c) => kindOf(c) === "wire").forEach((w) => { const t = terms(w); t.slice(1).forEach((k) => uni(t[0], k)); });
  const sig = st.board === "esp32" ? "D2" : "D13";
  const rootOf = (k) => (par.has(k) ? find(k) : null);
  const members = (root) => [...par.keys()].filter((k) => find(k) === root);
  const sigR = rootOf(sig), gndR = rootOf("GND");
  const mark = (c, status, msg, extra) => {
    const o = out.parts[c.id] || (out.parts[c.id] = { status: "ok", msg: "", kind: kindOf(c) });
    if (status === "bad" || (status === "warn" && o.status === "ok")) { o.status = status; o.msg = msg; }
    if (extra) Object.assign(o, extra);
  };
  comps.forEach((c) => mark(c, "ok", ""));
  const hasNets = nets.length > 0;
  const markN = (c, st, msg) => { (out.hints[c.id] = out.hints[c.id] || []).push(msg); };
  const rs = comps.filter((c) => kindOf(c) === "resistor"), ls = comps.filter((c) => kindOf(c) === "led");
  const rRoots = (r) => terms(r).map(rootOf);
  const allR = new Set(); rs.forEach((r) => rRoots(r).forEach((x) => x && allR.add(x)));
  let goodR = null, goodL = null;
  if (hasNets) {
    rs.forEach((r) => {
      const roots = rRoots(r);
      const mem = [].concat(...roots.map((x) => (x ? members(x) : []))).filter(isPinNode);
      const wrong = mem.find((p) => p !== sig && p !== "GND");
      if (wrong) markN(r, "bad", `Resistor on ${wrong}; it belongs on ${sig}`);
      else if (!roots.includes(sigR) || !sigR) markN(r, "bad", `Resistor is not connected to ${sig}`);
      else goodR = goodR || r;
    });
    ls.forEach((l) => {
      const ts = terms(l);
      const a = ts.find((k) => slotOf(l.id, k.split(".")[1], "led") === "a"), k = ts.find((x) => slotOf(l.id, x.split(".")[1], "led") === "k");
      const aR = a && rootOf(a), kR = k && rootOf(k);
      if ((kR && allR.has(kR) && kR !== gndR) || (aR && gndR && aR === gndR)) {
        markN(l, "bad", "LED is reversed: long leg (anode) toward the resistor, short leg to GND", { flip: true });
      } else if (!kR || !gndR || kR !== gndR) markN(l, "bad", "LED cathode (short leg) is not connected to GND");
      else if (rs.length && (!aR || !allR.has(aR))) markN(l, "warn", "LED anode is not connected to the resistor");
      else if (!rs.length) markN(l, "warn", "LED has no series resistor");
      else goodL = goodL || { l, aR };
    });
    if (goodR && goodL) {
      const other = rRoots(goodR).find((x) => x && x !== sigR);
      out.complete = !!(other && other === goodL.aR && out.parts[goodL.l.id].status === "ok" && out.parts[goodR.id].status === "ok");
    }
  }
  out.complete = !!(tw.led_lit === true);
  /* findings override / augment */
  arr(st.findings).concat(arr(st.mistakes).map((m) => (typeof m === "string" ? { severity: "error", message: m } : m && typeof m === "object" ? Object.assign({ severity: "error", message: m.message || m.title || m.id || "Mistake" }, m, { severity: m.severity === "warn" ? "warn" : "error" }) : null))).forEach((f) => {
    if (!f || (f.severity !== "error" && f.severity !== "warn")) return;
    const sev = f.severity === "error" ? "bad" : "warn";
    let hit = false;
    arr(f.parts).forEach((p) => comps.forEach((c) => { if (matches(p, c)) { hit = true; mark(c, sev, f.message || "Problem"); } }));
    arr(f.pins).forEach((p) => out.badPins.add(norm(p)));
    if (!hit) out.loose.push({ sev, message: f.message || "", pins: arr(f.pins) });
    if (sev === "bad") out.complete = false;
  });
  /* step satisfaction */
  const anyBad = Object.values(out.parts).some((p) => p.status === "bad");
  const steps = arr(st.project && st.project.steps);
  if (!steps.length) out.stepOk = out.complete;
  else {
    const tags = stepTags(steps, st.stepIndex);
    const has = (k) => comps.some((c) => kindOf(c) === k && out.parts[c.id].status !== "bad");
    out.stepOk = !anyBad && tags.size > 0 && [...tags].every((t) => (t === "wire" ? hasNets || has("wire") : has(t)));
  }
  if (anyBad || out.loose.some((l) => l.sev === "bad")) out.stepOk = false;
  return out;
}
function stepTags(steps, idx) {
  const tags = new Set();
  steps.slice(0, clamp(idx | 0, 0, steps.length - 1) + 1).forEach((s) => arr(s && s.parts).forEach((p) => {
    const q = String(p).toLowerCase();
    if (/led/.test(q)) tags.add("led"); else if (/res|ohm/.test(q)) tags.add("resistor"); else if (/wire|jump/.test(q)) tags.add("wire");
  }));
  return tags;
}

/* ---------- renderer state ---------- */
const H = { host: null, ready: false, loading: null, S: { board: "nano", project: null, stepIndex: 0, twin: null, findings: [], mistakes: [], eff: null }, twinRef: null, twinJson: "", twinAt: 0, age0: 0, hadFix: false, sig: "", boardKey: "", flashT: -9, flashKind: "ok" };
let R = null; // render context

function safe(fn, tag) { try { return fn(); } catch (e) { console.error("[scene3d]" + (tag ? " " + tag : ""), e); } }

/* canvas textures */
const texCache = new Map();
function textTex(text, o = {}) {
  const key = text + "|" + (o.color || "") + "|" + (o.rot || 0);
  if (texCache.has(key)) return texCache.get(key);
  const w = o.rot ? 48 : 128, h = o.rot ? 128 : 48, cv = document.createElement("canvas");
  cv.width = w; cv.height = h;
  const x = cv.getContext("2d");
  x.fillStyle = o.color || "#9fefff"; x.font = "bold 30px monospace"; x.textAlign = "center"; x.textBaseline = "middle";
  x.translate(w / 2, h / 2); if (o.rot) x.rotate(-Math.PI / 2);
  x.fillText(text, 0, 0);
  const t = new THREE.CanvasTexture(cv); t.userData.keep = true; t.colorSpace = THREE.SRGBColorSpace;
  texCache.set(key, t); return t;
}
function flatLabel(text, w, h, o) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: textTex(text, o), transparent: true, depthWrite: false, toneMapped: false }));
  m.rotation.x = -Math.PI / 2; return m;
}
function sprite(text, hex, scaleK = 60) {
  const lines = []; let cur = "";
  String(text).split(/\s+/).forEach((w) => { if ((cur + " " + w).length > 30) { lines.push(cur); cur = w; } else cur = (cur ? cur + " " : "") + w; });
  if (cur) lines.push(cur);
  const L = lines.slice(0, 4), cv = document.createElement("canvas"); cv.width = 512; cv.height = 34 * L.length + 28;
  const x = cv.getContext("2d"), col = "#" + hex.toString(16).padStart(6, "0");
  x.fillStyle = "rgba(4,10,20,.82)"; x.fillRect(0, 0, cv.width, cv.height);
  x.strokeStyle = col; x.lineWidth = 4; x.strokeRect(2, 2, cv.width - 4, cv.height - 4);
  x.fillStyle = col; x.font = "bold 26px monospace"; x.textBaseline = "middle";
  L.forEach((l, i) => x.fillText(l, 16, 30 + i * 34));
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true, toneMapped: false }));
  s.scale.set(cv.width / scaleK, cv.height / scaleK, 1); s.renderOrder = 20; return s;
}
function clearGroup(g) {
  for (let i = g.children.length - 1; i >= 0; i--) {
    const c = g.children[i]; g.remove(c);
    c.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.map && !m.map.userData.keep) m.map.dispose(); m.dispose(); });
    });
  }
}
const lineMat = (hex, op = 0.6) => new THREE.LineBasicMaterial({ color: hex, transparent: true, opacity: op });
function edges(mesh, hex, op) { const l = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), lineMat(hex, op)); mesh.add(l); return l; }

/* ---------- static scene: breadboard + boards ---------- */
function buildBreadboard() {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(31, 2, 19.4), new THREE.MeshPhysicalMaterial({ color: 0x0b1a2a, transparent: true, opacity: 0.6, roughness: 0.15, metalness: 0.2, clearcoat: 1 }));
  body.position.y = -1; g.add(body); edges(body, C.cyan, 0.7);
  const chan = new THREE.Mesh(new THREE.PlaneGeometry(30, 1.6), new THREE.MeshBasicMaterial({ color: 0x01040a })); chan.rotation.x = -Math.PI / 2; chan.position.y = 0.02; g.add(chan);
  const pts = [];
  for (let c = 1; c <= 30; c++) for (let r = 0; r < 10; r++) pts.push(holePos(c, ROWS[r]));
  [-8.3, -7.3, 7.3, 8.3].forEach((z) => { for (let b = 0; b < 5; b++) for (let k = 0; k < 5; k++) pts.push(new V3(-11.5 + b * 5 + k, 0, z)); });
  const holes = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.4, 0.4), new THREE.MeshBasicMaterial({ color: 0x1fb5d6, transparent: true, opacity: 0.75 }), pts.length);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
  pts.forEach((p, i) => { m4.compose(new V3(p.x, 0.03, p.z), q, new V3(1, 1, 1)); holes.setMatrixAt(i, m4); });
  g.add(holes);
  [[-8.9, C.red], [-6.7, 0x2f7bff], [6.7, 0x2f7bff], [8.9, C.red]].forEach(([z, col]) => {
    const s = new THREE.Mesh(new THREE.PlaneGeometry(25, 0.08), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.8 })); s.rotation.x = -Math.PI / 2; s.position.set(0, 0.03, z); g.add(s);
  });
  [1, 5, 10, 15, 20, 25, 30].forEach((c) => { const l = flatLabel(String(c), 1.6, 0.6, { color: "#5fb8cc" }); l.position.set(c - 15.5, 0.04, -6.5); g.add(l); });
  [...ROWS].forEach((r) => { const p = holePos(1, r), l = flatLabel(r, 1.2, 0.45, { color: "#5fb8cc" }); l.position.set(-15.1, 0.04, p.z); g.add(l); });
  [[7.3, "-", "#6aa8ff"], [8.3, "+", "#ff6a80"]].forEach(([z, t, col]) => { const l = flatLabel(t, 1, 0.6, { color: col }); l.position.set(-13, 0.04, z); g.add(l); });
  return g;
}

function buildBoard(key) {
  const B = BOARDS[key], g = new THREE.Group(), pinMeshes = {};
  const nano = key === "nano", w = nano ? 7 : 11, len = nano ? 16.6 : 18;
  const body = new THREE.Mesh(new THREE.BoxGeometry(len, 0.3, w), new THREE.MeshPhysicalMaterial({ color: nano ? 0x08204a : 0x0c1b22, transparent: true, opacity: 0.8, roughness: 0.3, metalness: 0.4, clearcoat: 1 }));
  body.position.set(0, 0.4, B.cz); g.add(body); edges(body, C.cyan, 0.9);
  const add = (geo, hex, x, y, z, edge) => { const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: hex, roughness: 0.4, metalness: 0.7 })); m.position.set(x, y, z); g.add(m); if (edge) edges(m, C.cyan, 0.8); return m; };
  if (nano) {
    add(new THREE.BoxGeometry(2.6, 1.2, 3.4), 0x5a6a7c, -9.0, 0.95, B.cz);
    add(new THREE.BoxGeometry(3.2, 0.3, 3.2), 0x05080c, 1, 0.7, B.cz, true);
    add(new THREE.BoxGeometry(1.2, 0.3, 1.2), 0x05080c, -4, 0.7, B.cz + 1.2, true);
  } else {
    add(new THREE.BoxGeometry(6.2, 0.5, 5), 0x9aa8b4, -5.6, 0.8, B.cz, true);
    add(new THREE.BoxGeometry(1.8, 0.7, 3), 0xb8c4d0, 9.4, 0.85, B.cz);
    add(new THREE.BoxGeometry(2.4, 0.3, 2.4), 0x05080c, 3, 0.7, B.cz, true);
    add(new THREE.BoxGeometry(1, 0.5, 1), 0xb8c4d0, 6, 0.8, B.cz - 3.6); add(new THREE.BoxGeometry(1, 0.5, 1), 0xb8c4d0, 6, 0.8, B.cz + 3.6);
  }
  [["right", -1], ["left", 1]].forEach(([side, sgn]) => {
    B[side].forEach((n, i) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.9, 0.34), new THREE.MeshStandardMaterial({ color: 0xc0c4cc, metalness: 0.8, roughness: 0.3, emissive: 0x000000 }));
      m.position.set(i - 7, 0.55, B.cz + sgn * B.half); g.add(m); pinMeshes[n] = m;
      const l = flatLabel(n.replace(/_[LR]$/, ""), 0.9, 2.2, { rot: true, color: /^GND/.test(n) ? "#7aa0ff" : /5V|3V3|VIN/.test(n) ? "#ff7a8a" : "#9fefff" });
      l.position.set(i - 7, 0.57, B.cz + sgn * (B.half - 1.5)); g.add(l);
    });
  });
  const tag = flatLabel(B.label, 5, 0.7, { color: "#3a8fa6" }); tag.position.set(nano ? 4 : 0, 0.57, B.cz + (nano ? 1.6 : 2.5)); g.add(tag);
  g.position.x = 0.5; // pin pitch lines up with breadboard columns
  g.userData.pinMeshes = pinMeshes;
  return g;
}

/* ---------- part builders ---------- */
function gMat(hex, op) { return new THREE.MeshBasicMaterial({ color: hex, wireframe: true, transparent: true, opacity: op, depthWrite: false }); }
function sMat(hex, e = 0.35, extra) { return new THREE.MeshStandardMaterial(Object.assign({ color: hex, emissive: hex, emissiveIntensity: e, roughness: 0.35, metalness: 0.3 }, extra)); }
function track(list, mats, base, cur) { list.push({ mats, base, cur, ph: Math.random() * 6 }); }

function buildLED(mode, hex, a, k, flip, pulsers) {
  const g = new THREE.Group(), mid = a.clone().add(k).multiplyScalar(0.5), ghost = mode === "ghost";
  const mats = [];
  const M = (h, e) => { const m = ghost ? gMat(hex, 0.6) : sMat(h, e); if (ghost) mats.push(m); return m; };
  const dome = new THREE.Mesh(new THREE.SphereGeometry(0.75, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), ghost ? M() : new THREE.MeshPhysicalMaterial({ color: hex, emissive: hex, emissiveIntensity: 0.25, transparent: true, opacity: 0.8, roughness: 0.1 }));
  dome.position.set(mid.x, 2.25, mid.z);
  const cyl = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.75, 1.3, 20), dome.material);
  cyl.position.set(mid.x, 1.6, mid.z);
  const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.92, 0.92, 0.15, 20), M(hex, 0.3)); rim.position.set(mid.x, 0.95, mid.z);
  g.add(dome, cyl, rim);
  const longP = flip ? k : a, shortP = flip ? a : k;
  [[longP, 2.3, true], [shortP, 1.6, false]].forEach(([p, h, isLong]) => {
    const curve = new THREE.CatmullRomCurve3([new V3(p.x, -0.5, p.z), new V3(p.x, 0.5, p.z), new V3(mid.x + (p.x - mid.x) * 0.5, 1.0, mid.z)]);
    g.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 8, 0.07, 5), ghost ? M() : sMat(0xdde6ee, 0.1)));
    if (isLong) { const pl = sprite("+", hex, 90); pl.scale.multiplyScalar(0.0 + 0.5); pl.position.set(p.x, 3.5, p.z); pl.material.depthTest = true; if (!ghost) g.add(pl); }
  });
  if (!ghost) { const flat = new THREE.Mesh(new THREE.BoxGeometry(0.1, 1.3, 1.1), sMat(hex, 0.1)); flat.position.set(shortP.x + (mid.x - shortP.x) * 0.2 - 0.0, 1.6, shortP.z); flat.position.x = mid.x + (shortP.x - mid.x) * 0.95; g.add(flat); }
  if (ghost) track(pulsers.list, mats, 0.6, pulsers.cur);
  g.userData.dome = dome.material; g.userData.center = new V3(mid.x, 2.2, mid.z);
  return g;
}
function buildResistor(mode, hex, a, b, pulsers, val) {
  const g = new THREE.Group(), ghost = mode === "ghost", mats = [];
  const M = (h, e) => { const m = ghost ? gMat(hex, 0.6) : sMat(h, e); if (ghost) mats.push(m); return m; };
  const mid = a.clone().add(b).multiplyScalar(0.5), d = b.clone().sub(a).setY(0).normalize();
  const body = new THREE.Group(); body.position.set(mid.x, 1.3, mid.z); body.quaternion.setFromUnitVectors(new V3(0, 1, 0), d);
  body.add(new THREE.Mesh(new THREE.CapsuleGeometry(0.38, 1.6, 4, 12), M(0xd9b98a, 0.15)));
  if (!ghost) (() => { const bd = resBands(val); return [[-0.55, bd[0]], [-0.2, bd[1]], [0.15, bd[2]], [0.6, 0xd4af37]]; })().forEach(([y, c]) => { const r = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.12, 12), sMat(c, 0.2)); r.position.y = y; body.add(r); });
  g.add(body);
  const up = (p, y) => new V3(p.x, y, p.z);
  const pts = [up(a, -0.5), up(a, 1.0), up(mid, 1.3).addScaledVector(d, -1.1), up(mid, 1.3).addScaledVector(d, 1.1), up(b, 1.0), up(b, -0.5)];
  g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.1), 40, 0.07, 5), ghost ? M() : sMat(0xdde6ee, 0.1)));
  if (ghost) track(pulsers.list, mats, 0.6, pulsers.cur);
  g.userData.center = new V3(mid.x, 1.5, mid.z);
  return g;
}
function buildWire(mode, hex, from, to, pulsers) {
  const g = new THREE.Group(), ghost = mode === "ghost";
  const len = from.distanceTo(to), mid = from.clone().add(to).multiplyScalar(0.5); mid.y = 0.9 + len * 0.16;
  const up = (p) => new V3(p.x, Math.max(p.y, 0) + 0.7, p.z);
  const curve = new THREE.CatmullRomCurve3([from.clone(), up(from), mid, up(to), to.clone()], false, "centripetal");
  const m = ghost ? gMat(hex, 0.55) : sMat(hex, 0.35);
  g.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 48, ghost ? 0.1 : 0.13, 6), m));
  if (!ghost) [from, to].forEach((p) => { const s = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 8), sMat(0xdde6ee, 0.2)); s.position.copy(p); g.add(s); });
  else track(pulsers.list, [m], 0.55, pulsers.cur);
  g.userData.center = mid.clone(); g.userData.curve = curve;
  return g;
}

/* ---------- generic part model (local coords: terminal 'first' at origin) ---------- */
const TERM = {
  resistor: { a: [0, 0], b: [4, 0] }, led: { a: [0, 0], k: [1, 0] },
  button: { a: [0, 0], b: [2, 0], c: [0, 2], d: [2, 2] }, buzzer: { pos: [0, 0], neg: [2, 0] },
  pot: { p1: [0, 0], wiper: [1.5, 0], p3: [3, 0] }, ic: { t0: [0, 0], t1: [1, 0], t2: [2, 0], t3: [3, 0] },
  wire: { a: [0, 0], b: [1.5, 2.8] },
};
const hashN = (s) => { let h = 0; for (const ch of String(s)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h; };
function termOf(kind, t) {
  t = String(t || "").toLowerCase(); const T = TERM[kind] || TERM.ic;
  if (T[t]) return t;
  const keys = Object.keys(T);
  if (kind === "led") return /^(a|anode|\+|pos|long|1)/.test(t) ? "a" : "k";
  if (kind === "resistor" || kind === "wire") return /^(a|1|p1|in|from)$/.test(t) ? "a" : "b";
  if (kind === "buzzer") return /^(pos|\+|a|1|plus|p|vcc|sig)/.test(t) ? "pos" : "neg";
  if (kind === "pot") return /wiper|^w$|out|sig|mid|^2$|^b$/.test(t) ? "wiper" : /^(1|a|vcc|top|hi|p1)/.test(t) ? "p1" : "p3";
  return keys[hashN(t) % keys.length];
}
function termLocal(kind, t) { const T = TERM[kind] || TERM.ic, o = T[termOf(kind, t)] || [0, 0]; return new V3(o[0], 0, o[1]); }
function partKindOf(s) {
  s = String(s == null ? "" : s).toLowerCase().trim();
  if (!s) return null;
  if (/breadboard|bread board/.test(s)) return "breadboard";
  if (/esp|arduino|nano|uno|mega|devkit|microcontroller/.test(s)) return "board";
  if (/led|diode/.test(s) || /^l\d+$/.test(s)) return "led";
  if (/buzz|speaker|piezo/.test(s)) return "buzzer";
  if (/btn|button|switch|^sw\d*$|push/.test(s)) return "button";
  if (/pot|trimmer|^vr\d|^rv\d|rheostat/.test(s)) return "pot";
  if (/res|ohm|^r\d+$/.test(s)) return "resistor";
  if (/wire|jump|cable/.test(s)) return "wire";
  if (/\bic\b|chip|sensor|^u\d|servo|motor|display|lcd|oled|relay|module|transistor|^q\d/.test(s)) return "ic";
  return null;
}
const LEDCOL = { red: 0xff3030, green: 0x30ff60, blue: 0x3a7bff, yellow: 0xffe03a, white: 0xf4f8ff, orange: 0xff8a1f, amber: 0xffb21e, purple: 0xb060ff, pink: 0xff70c0 };
const BAND = [0x111111, 0x7a3b10, 0xe02020, 0xff8a1f, 0xffe03a, 0x31d46b, 0x2f7bff, 0xa855f7, 0x9aa5b1, 0xf4f4f4];
function resBands(val) {
  const m = /^\s*([\d.]+)\s*([kKmM]?)/.exec(String(val == null ? "220" : val));
  if (!m) return [0xe02020, 0xe02020, 0x7a3b10];
  let v = parseFloat(m[1]) * ({ k: 1e3, m: 1e6 }[m[2].toLowerCase()] || 1);
  if (!(v >= 1)) return [0xe02020, 0xe02020, 0x7a3b10];
  let e = 0; while (v >= 100 && e < 9) { v /= 10; e++; }
  while (v < 10 && v > 0 && e > -2) { v *= 10; e--; }
  const r = Math.round(v);
  return [BAND[Math.floor(r / 10) % 10], BAND[r % 10], e >= 0 ? BAND[e] : (e === -1 ? 0xd4af37 : 0xc0c0c0)];
}
function boxy(mode, hex, w, h, d, cx, cy, cz, pulsers, kids) {
  const g = new THREE.Group(), ghost = mode === "ghost", mats = [];
  const M = (c, e) => { const m = ghost ? gMat(hex, 0.6) : sMat(c, e); if (ghost) mats.push(m); return m; };
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), M(hex, 0.15)); b.position.set(cx, cy, cz); g.add(b);
  if (kids) kids(g, M);
  if (ghost && pulsers) track(pulsers.list, mats, 0.6, pulsers.cur);
  g.userData.center = new V3(cx, cy + 1.2, cz); return g;
}
function buildPart(kind, mode, hex, o, pulsers) {
  o = o || {};
  if (kind === "resistor") return buildResistor(mode, hex, new V3(0, 0, 0), new V3(4, 0, 0), pulsers, o.val);
  if (kind === "led") return buildLED(mode, hex, new V3(0, 0, 0), new V3(1, 0, 0), false, pulsers);
  if (kind === "wire") return buildWire(mode, hex, new V3(0, 0, 0), new V3(1.5, 0, 2.8), pulsers);
  const col = mode === "ghost" ? C.cyan : 0x9fb4c8;
  if (kind === "button") return boxy(mode, col, 2.4, 0.9, 2.4, 1, 0.9, 1, pulsers, (g, M) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.7, 0.5, 16), M(0xff4060, 0.3)); c.position.set(1, 1.5, 1); g.add(c); });
  if (kind === "buzzer") return boxy(mode, 0x202830, 0.01, 0.01, 0.01, 1, 0.5, 0, pulsers, (g, M) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 1.3, 20), M(mode === "ghost" ? C.cyan : 0x23303c, 0.2)); c.position.set(1, 1.0, 0); g.add(c); const h = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.1, 10), M(0x000000, 0)); h.position.set(1, 1.7, 0); g.add(h); });
  if (kind === "pot") return boxy(mode, 0x1f5fb0, 3.6, 1.0, 2.2, 1.5, 0.9, 0, pulsers, (g, M) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 0.9, 14), M(0xd0d8e0, 0.15)); c.position.set(1.5, 1.7, 0); g.add(c); });
  return boxy(mode, 0x1a1f26, 3.6, 0.9, 1.8, 1.5, 0.8, 0.5, pulsers);
}
function ghostParts(steps, idx, L) {
  const map = new Map(), generic = new Set();
  const skip = (k) => !k || k === "wire" || k === "board" || k === "breadboard";
  steps.slice(0, idx + 1).forEach((s) => {
    arr(s.parts).forEach((p) => {
      const q = String(p == null ? "" : p).trim(), m = /^([A-Za-z]+\d+)\b/.exec(q), k = partKindOf(m ? m[1] : q) || partKindOf(q);
      if (skip(k)) return; if (m && partKindOf(m[1])) map.set(m[1].toUpperCase(), { kind: k }); else generic.add(k);
    });
    arr(s.wires).forEach((w) => [w && w.from, w && w.to].forEach((e) => {
      const m = /^([A-Za-z]+\d+)[._](\w+)$/.exec(String(e == null ? "" : e)); if (!m) return;
      const k = partKindOf(m[1]) || "ic"; if (!skip(k) && !isPinNode(norm(m[1]))) map.set(m[1].toUpperCase(), { kind: k });
    }));
  });
  generic.forEach((k) => { if (![...map.values()].some((v) => v.kind === k)) map.set(k.toUpperCase() + "1", { kind: k }); });
  const cnt = {}; let gi = 0;
  map.forEach((p) => { const n = cnt[p.kind] = (cnt[p.kind] === undefined ? 0 : cnt[p.kind] + 1); p.slot = slotFor(p.kind, n, gi, L); if (p.kind !== "resistor" && p.kind !== "led") gi++; });
  return map;
}
function slotFor(kind, n, m, L) {
  if (kind === "resistor") return n === 0 ? L.r.a.clone() : holePos(3 + (6 * (n - 1)) % 22, "A");
  if (kind === "led") return n === 0 ? L.led.a.clone() : holePos(4 + (3 * (n - 1)) % 24, "G");
  if (kind === "wire") return holePos(3 + (2 * n) % 25, "J");
  return holePos(4 + (5 * m) % 22, "I");
}

/* ---------- dynamic build ---------- */
function endpointPos(raw, L, board, gp) {
  const s = String(raw == null ? "" : raw), h = parseHole(s);
  if (h) return holePos(h.col, h.row);
  const u = norm(s);
  if (/^(GND_?RAIL|RAIL|BB[_-]?GND|-RAIL|RAIL-)$/.test(u)) return L.rail.clone();
  const m = /^([A-Z]+\d*)[._](\w+)$/.exec(u);
  if (m && gp && gp.has(m[1])) { const p = gp.get(m[1]); return p.slot.clone().add(termLocal(p.kind, m[2])); }
  const p = resolvePin(board, s);
  return p ? p.pos : null;
}
function wireColor(c, d) { return WIRE_COL[String(c || "").toLowerCase()] || d; }
const effBoard = () => (BOARDS[H.S.eff] ? H.S.eff : BOARDS[H.S.board] ? H.S.board : "nano");
function twinBoard(tw) {
  if (!tw || tw.scene === "other") return null;
  for (const c of arr(tw.components)) {
    if (!c || typeof c !== "object") continue;
    const s = (String(c.type) + " " + String(c.id)).toLowerCase();
    if (/esp/.test(s)) return "esp32"; if (/arduino|nano|uno/.test(s)) return "nano";
  }
  return null;
}
function prep(g) {
  g.traverse((o) => { if (!o.material) return; (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.userData.o0 === undefined) { m.userData.o0 = m.opacity; m.transparent = true; } }); });
}
function disposeObj(w) { if (w.parent) w.parent.remove(w); w.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.map && !m.map.userData.keep) m.map.dispose(); m.dispose(); }); }); }

function syncLive(S, an, L, board) {
  const tw = S.twin, tick = (R.tick = (R.tick || 0) + 1), comps = tw && Array.isArray(tw.components) ? tw.components : [];
  const placeOf = (id) => { const p = arr(tw && tw.placements).find((x) => x && typeof x === "object" && norm(x.id) === norm(id)); return p ? parseHole(p.hole) : null; };
  const cnt = {}; let gi = 0, wi = 0;
  const seenKeys = new Set();
  comps.forEach((c, i) => {
    if (!c || typeof c !== "object") return;
    const kind = kindOf(c); if (kind === "board" || kind === "breadboard") return;
    const id = c.id != null ? String(c.id) : kind + "#" + i; let key = norm(id); if (seenKeys.has(key)) key += "#" + i; seenKeys.add(key);
    const n = cnt[kind] = (cnt[kind] === undefined ? 0 : cnt[kind] + 1);
    const info = an.parts[c.id] || { status: "ok" };
    let slot = kind === "wire" ? slotFor("wire", wi++, 0, L) : slotFor(kind, n, gi, L);
    if (kind !== "resistor" && kind !== "led" && kind !== "wire") gi++;
    const ph = placeOf(id);
    if (ph && (kind === "resistor" ? ph.col <= 26 : kind === "led" ? ph.col <= 29 : false)) slot = holePos(ph.col, ph.row);
    const val = c.value != null ? String(c.value) : "";
    const hex = kind === "led" ? (LEDCOL[String(c.color || val).toLowerCase()] || 0xff3030) : kind === "wire" ? wireColor(c.color || val, 0xff8a1f) : 0x9fb4c8;
    const sig = [kind, hex, val, info.status].join("|");
    let e = R.live.get(key);
    if (!e || e.sig !== sig) {
      const g = buildPart(kind, "solid", hex, { val }, null); prep(g);
      const w = new THREE.Group(); w.add(g); R.gObs.add(w);
      if (e) { disposeObj(e.w); e.w = w; } else { e = { w, cur: slot.clone(), tgt: slot.clone(), alpha: 0, aTgt: 1 }; R.live.set(key, e); }
      e.w = w; e.sig = sig; e.kind = kind; e.dome = g.userData.dome || null; e.center = g.userData.center;
    }
    e.tgt.copy(slot); e.aTgt = 1; e.seen = tick; e.kindTag = kind; e.id = id;
    const lit = !!(tw && tw.led_lit === true); e.lit = lit; e.ledHex = hex;
    if (info.status !== "ok") {
      const hx = C.amber, ctr = slot.clone().add(new V3(e.center.x, e.center.y, e.center.z));
      const h = new THREE.Mesh(new THREE.SphereGeometry(kind === "led" ? 1.8 : 2.3, 16, 12), new THREE.MeshBasicMaterial({ color: hx, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, depthWrite: false }));
      h.position.copy(ctr); R.gLabels.add(h); R.halos.push(h);
      const sp = sprite("! " + (info.msg || "Check this part"), hx); sp.position.set(ctr.x, ctr.y + 3.2, ctr.z); R.gLabels.add(sp);
    }
  });
  R.live.forEach((e) => { if (e.seen !== tick) e.aTgt = 0; });
  /* unverified nets as thin dashed cyan hints */
  const legs = (name) => {
    const u = norm(name), m = /^(.+?)\.(.+)$/.exec(u);
    if (m) { for (const [k, e] of R.live) if (k === m[1] || k.startsWith(m[1] + "#")) return e.tgt.clone().add(termLocal(e.kind, m[2])).setY(0.4); return null; }
    const p = resolvePin(board, name); if (p) return p.pos.clone(); const h = parseHole(name); return h ? holePos(h.col, h.row) : null;
  };
  R.hasNets = false;
  arr(tw && tw.nets).filter(Array.isArray).slice(0, 40).forEach((n) => {
    const ps = n.map((x) => (typeof x === "string" ? legs(x) : null)).filter(Boolean);
    for (let i = 1; i < ps.length; i++) {
      if (ps[i - 1].distanceTo(ps[i]) < 0.05) continue;
      const a = ps[i - 1].clone().setY(Math.max(ps[i - 1].y, 0.5) + 0.4), b = ps[i].clone().setY(Math.max(ps[i].y, 0.5) + 0.4), mid = a.clone().add(b).multiplyScalar(0.5).setY(a.y + 1.2);
      const ln = new THREE.Line(new THREE.BufferGeometry().setFromPoints(new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(16)), new THREE.LineDashedMaterial({ color: C.cyan, dashSize: 0.32, gapSize: 0.26, transparent: true, opacity: 0.6 }));
      ln.computeLineDistances(); R.gNets.add(ln); R.hasNets = true;
    }
  });
}
function updateLive(dt, now) {
  const age = twinAge(), other = !!(H.S.twin && H.S.twin.scene === "other"), none = !H.S.twin;
  const dimT = none || other ? 0 : age > 15 ? 0.3 : 1;
  R.dim += (dimT - R.dim) * Math.min(1, dt * 5);
  const k = 1 - Math.exp(-dt * 8), da = dt / 0.4, dead = [];
  let firstLed = null;
  R.live.forEach((e, key) => {
    e.cur.lerp(e.tgt, k); e.w.position.copy(e.cur);
    e.alpha += Math.sign(e.aTgt - e.alpha) * Math.min(Math.abs(e.aTgt - e.alpha), da);
    const a = e.alpha * R.dim; e.w.visible = a > 0.01;
    e.w.traverse((o) => { if (!o.material) return; (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.userData.o0 !== undefined) m.opacity = m.userData.o0 * a; }); });
    if (e.alpha <= 0.001 && e.aTgt === 0) dead.push(key);
    if (e.kind === "led" && e.dome) {
      const on = e.lit && (Math.sin(now * 6) > -0.4 || true);
      e.dome.emissive.setHex(e.ledHex); e.dome.emissiveIntensity = e.lit ? 2.2 + 1.2 * Math.sin(now * 5) : 0.2;
      if (e.lit && !firstLed) firstLed = e;
    }
  });
  dead.forEach((key) => { disposeObj(R.live.get(key).w); R.live.delete(key); });
  if (firstLed) { R.ledLight.color.setHex(firstLed.ledHex); R.ledLight.intensity = 40 * R.dim; R.ledLight.position.copy(firstLed.cur).add(new V3(0.5, 3, 0)); } else R.ledLight.intensity = 0;
  R.gLabels.visible = R.dim > 0.5; R.gNets.visible = R.dim > 0.15;
  R.gNets.children.forEach((l) => (l.material.opacity = 0.6 * R.dim));
  if (R.liveEl) {
    const stale = !none && !other && age > 15;
    R.liveEl.innerHTML = none ? '<span style="color:#7a8a99">NO TWIN YET</span>' : other ? '<span style="color:#ffb21e">&#9679; NO SCENE</span>' : stale ? `<span style="color:#ffb21e">&#9679; STALE &middot; seen ${Math.round(age)} s ago</span>` : `<span style="color:#3dff8f">&#9679; LIVE</span> &middot; seen ${Math.max(0, Math.round(age))} s ago`;
    if (R.hasNets && !other && !none) R.liveEl.innerHTML += '<br><span style="color:#19e3ff;opacity:.8">- - unverified nets</span>';
    R.msgEl.style.display = other ? "block" : "none";
  }
}
function twinAge() { return H.S.twin ? (performance.now() - H.twinAt) / 1000 + (H.age0 || 0) : Infinity; }

function rebuildDynamic() {
  const { S } = H, board = effBoard(), B = BOARDS[board];
  clearGroup(R.gTarget); clearGroup(R.gLabels); clearGroup(R.gNets);
  R.pulsers = []; R.halos = []; R.activePins = new Set(); R.badPins = new Set(); R.flow = null;
  const L = defaultLayout(board), an = analyze(Object.assign({}, S, { board }));
  R.an = an;
  /* ---- TARGET ---- */
  const steps = arr(S.project && S.project.steps).filter((s) => s && typeof s === "object");
  const idx = steps.length ? clamp(S.stepIndex | 0, 0, steps.length - 1) : 0;
  const defW = { sig: { f: L.sig, t: L.sigHole, c: "orange" }, g1: { f: L.gndHole, t: L.rail, c: "black" }, g2: { f: L.railPin, t: L.gnd, c: "black" } };
  const wires = [];
  let gp;
  if (!steps.length) { wires.push(["sig", true], ["g1", true], ["g2", true]); gp = new Map([["R1", { kind: "resistor", slot: L.r.a.clone() }], ["LED1", { kind: "led", slot: L.led.a.clone() }]]); }
  else {
    gp = ghostParts(steps, idx, L);
    const seen = new Set();
    steps.slice(0, idx + 1).forEach((s, si) => {
      const cur = si === idx;
      arr(s.wires).forEach((w) => {
        if (!w) return;
        const f = endpointPos(w.from, L, board, gp), t = endpointPos(w.to, L, board, gp);
        if (f && t) wires.push([{ f, t, c: w.color }, cur]);
        else {
          const touchesSig = [w.from, w.to].some((x) => norm(x) === B.sig || (norm(x) === "GPIO2" && board === "esp32"));
          (touchesSig ? ["sig"] : ["g1", "g2"]).forEach((id) => { if (!seen.has(id)) { seen.add(id); wires.push([id, cur]); } });
        }
      });
      if (cur) arr(s.pins).forEach((p) => { const r = resolvePin(board, p); if (r) R.activePins.add(r.name); });
    });
  }
  const P = (cur) => ({ list: R.pulsers, cur });
  wires.forEach(([w, cur]) => { const d = typeof w === "string" ? defW[w] : w; R.gTarget.add(buildWire("ghost", C.cyan, d.f, d.t, P(cur))); });
  gp.forEach((p) => { const g = buildPart(p.kind, "ghost", C.cyan, {}, P(true)); g.position.copy(p.slot); R.gTarget.add(g); });
  if (!steps.length) R.activePins.add(B.sig), R.activePins.add(B.gnd);
  an.badPins.forEach((p) => { const r = resolvePin(board, p); if (r) R.badPins.add(r.name); });

  /* ---- OBSERVED (persistent, tweened) ---- */
  syncLive(S, an, L, board);
  if (an.complete) {
    const f = (kind) => { for (const e of R.live.values()) if (e.kind === kind && e.aTgt === 1) return e.tgt; return null; };
    const rt = f("resistor") || L.r.a, lt = f("led") || L.led.a, up = (p, y) => new V3(p.x, y, p.z);
    const pts = [L.sig, up(L.sig, 2.5), up(rt, 2.0), up(rt.clone().add(new V3(4, 0, 0)), 1.2), up(lt, 1.0), up(lt.clone().add(new V3(1, 0, 0)), 1.0), up(L.gndHole, 1.0), up(L.rail, 1.0), up(L.railPin, 1.0), L.gnd.clone()];
    const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal");
    const im = new THREE.InstancedMesh(new THREE.SphereGeometry(0.17, 8, 8), new THREE.MeshBasicMaterial({ color: C.green, blending: THREE.AdditiveBlending, transparent: true, toneMapped: false }), 44);
    R.gLabels.add(im); R.flow = { im, curve };
    R.gLabels.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 160, 0.05, 5), new THREE.MeshBasicMaterial({ color: C.green, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false })));
  }
  /* findings without a part: label at pin / above board */
  an.loose.slice(0, 3).forEach((l, i) => {
    const hex = C.amber, p = l.pins.map((x) => resolvePin(board, x)).find(Boolean);
    const s = sprite("! " + l.message, hex); const base = p ? p.pos : new V3(0, 0, -9);
    s.position.set(base.x, base.y + 3.5 + (p ? 0 : i * 2.2), base.z); R.gLabels.add(s);
  });
  const fixes = computeFixes(S, an, L, board, steps, idx, gp);
  buildFixes(fixes);
  if (!fixes.length && H.hadFix) flash("ok");
  H.hadFix = fixes.length > 0;
  R.shimmer.visible = an.stepOk;
  updateHud(steps, idx, an);
}
function updateHud(steps, idx, an) {
  if (!R.hud) return;
  const parts = Object.values(an.parts), bad = parts.filter((p) => p.status === "bad").length + an.loose.filter((l) => l.sev === "bad").length;
  const st = steps[idx] ? `STEP ${idx + 1}/${steps.length}${steps[idx].title ? " · " + steps[idx].title : ""}` : "BLINK · TARGET";
  const state = !H.S.twin ? "NO TWIN" : an.complete ? "CIRCUIT COMPLETE" : bad ? "CHECK " + bad + " POSSIBLE ISSUE" + (bad > 1 ? "S" : "") : an.stepOk ? "STEP OK" : "BUILDING";
  const col = an.complete || an.stepOk ? "#3dff8f" : bad ? "#ff2d55" : "#19e3ff";
  R.hud.innerHTML = `<div style="color:#19e3ff">◇ TARGET (ghost) &nbsp; <span style="color:#d8f4ff">◆ OBSERVED (solid)</span></div><div style="opacity:.85">${st.replace(/</g, "&lt;")}</div><div style="color:${col}">${state}</div>`;
}

/* ---------- init / loop ---------- */
async function init() {
  await loadLibs();
  V3 = THREE.Vector3;
  Object.keys(BOARDS).forEach((k) => (TABLE[k] = pinTable(k)));
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
  const scene = new THREE.Scene(); scene.background = new THREE.Color(C.bg); scene.fog = new THREE.FogExp2(C.bg, 0.011);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400); camera.position.set(0, 24, 38);
  scene.add(new THREE.AmbientLight(0x6688aa, 0.9));
  const dl = new THREE.DirectionalLight(0x9fefff, 1.4); dl.position.set(10, 30, 15); scene.add(dl);
  const pl = new THREE.PointLight(C.mag, 60, 60); pl.position.set(-18, 8, 10); scene.add(pl);
  const ledLight = new THREE.PointLight(C.green, 0, 14); scene.add(ledLight);
  const grid = new THREE.GridHelper(140, 70, 0x0e6a88, 0x07202e); grid.position.y = -2.6; grid.material.transparent = true; grid.material.opacity = 0.5; scene.add(grid);
  const shimmer = new THREE.Mesh(new THREE.PlaneGeometry(30, 18), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { t: { value: 0 }, c: { value: new THREE.Color(C.green) } },
    vertexShader: "varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}",
    fragmentShader: "uniform float t; uniform vec3 c; varying vec2 vUv; void main(){float x=fract(vUv.x-t*.3);float b=exp(-pow((x-.5)*9.,2.));float g=step(.95,fract(vUv.x*30.))+step(.9,fract(vUv.y*10.));gl_FragColor=vec4(c,.05+b*.25+g*.07*(.4+b));}",
  }));
  shimmer.rotation.x = -Math.PI / 2; shimmer.position.set(0, 0.12, 0); shimmer.visible = false; scene.add(shimmer);
  const gStatic = new THREE.Group(), gBoard = new THREE.Group(), gTarget = new THREE.Group(), gObs = new THREE.Group(), gLabels = new THREE.Group(), gNets = new THREE.Group(), gFix = new THREE.Group();
  gStatic.add(buildBreadboard());
  scene.add(gStatic, gBoard, gTarget, gObs, gLabels, gNets, gFix);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 5); controls.enableDamping = true; controls.autoRotate = false; controls.autoRotateSpeed = 0.8; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 12; controls.maxDistance = 90;
  controls.addEventListener("start", () => { controls.autoRotate = false; syncTb(); });
  let composer = null, bloom = null;
  if (EffectComposer) safe(() => {
    composer = new EffectComposer(renderer); composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.8, 0.55, 0.3); composer.addPass(bloom); composer.addPass(new OutputPass());
  }, "bloom");
  R = { renderer, scene, camera, controls, composer, bloom, gBoard, gTarget, gObs, gLabels, gNets, gFix, live: new Map(), dim: 0, fixes: [], shimmer, grid, ledLight, pulsers: [], halos: [], activePins: new Set(), badPins: new Set(), flow: null, led: null, an: null, clock: new THREE.Clock(), pinMeshes: {}, hud: null, ro: null };
  attach();
  H.ready = true;
  applyState(true);
  loop();
}
function attach() {
  if (!R || !H.host) return;
  const host = H.host;
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  const cv = R.renderer.domElement; cv.style.cssText = "display:block;width:100%;height:100%;outline:none";
  if (cv.parentNode !== host) host.appendChild(cv);
  if (!R.hud) { R.hud = document.createElement("div"); R.hud.style.cssText = "position:absolute;left:12px;top:34px;font:11px/1.5 ui-monospace,Menlo,monospace;letter-spacing:.08em;pointer-events:none;text-shadow:0 0 8px #000;z-index:2"; }
  if (R.hud.parentNode !== host) host.appendChild(R.hud);
  if (!R.liveEl) {
    R.liveEl = document.createElement("div"); R.liveEl.style.cssText = "position:absolute;right:12px;top:10px;text-align:right;font:11px/1.5 ui-monospace,Menlo,monospace;letter-spacing:.08em;pointer-events:none;color:#9fefff;text-shadow:0 0 8px #000;z-index:2";
    R.msgEl = document.createElement("div"); R.msgEl.textContent = "NO BOARD IN VIEW"; R.msgEl.style.cssText = "display:none;position:absolute;left:50%;top:42%;transform:translate(-50%,-50%);font:bold 20px ui-monospace,Menlo,monospace;letter-spacing:.2em;color:#ffb21e;text-shadow:0 0 14px #ffb21e;pointer-events:none;z-index:2";
    R.tb = buildToolbar();
  }
  [R.liveEl, R.msgEl, R.tb].forEach((e) => { if (e.parentNode !== host) host.appendChild(e); });
  if (R.ro) R.ro.disconnect();
  const size = () => {
    const w = Math.max(host.clientWidth, 2), h = Math.max(host.clientHeight, 2);
    R.renderer.setSize(w, h, false); R.camera.aspect = w / h; R.camera.updateProjectionMatrix();
    if (R.composer) { R.composer.setSize(w, h); R.composer.setPixelRatio && R.composer.setPixelRatio(R.renderer.getPixelRatio()); }
  };
  R.ro = new ResizeObserver(size); R.ro.observe(host); size();
}
function applyState(force) {
  if (!R) return;
  safe(() => {
    if (force || H.boardKey !== effBoard()) {
      const key = effBoard(); H.boardKey = key;
      clearGroup(R.gBoard); const b = buildBoard(key); R.gBoard.add(b); R.pinMeshes = b.userData.pinMeshes; H.sig = "";
    }
    const sig = JSON.stringify([effBoard(), H.S.project, H.S.stepIndex, H.S.twin, H.S.findings, H.S.mistakes]);
    if (sig !== H.sig) { H.sig = sig; rebuildDynamic(); }
  }, "apply");
}
function loop() {
  requestAnimationFrame(loop);
  safe(() => {
    const now = performance.now() / 1000;
    R.controls.update();
    const dtl = Math.min(0.1, now - (R.prevT || now)); R.prevT = now;
    updateLive(dtl, now); updateFix(now);
    R.pulsers.forEach((p) => { const o = p.base * (p.cur ? 0.6 + 0.4 * Math.sin(now * 3 + p.ph) : 0.45); p.mats.forEach((m) => (m.opacity = o)); });
    R.halos.forEach((h, i) => { const s = 1 + 0.22 * Math.sin(now * 5 + i); h.scale.setScalar(1); h.material.opacity = 0.22; });
    const pm = R.pinMeshes;
    for (const n in pm) {
      const m = pm[n].material, bad = R.badPins.has(n), act = R.activePins.has(n);
      if (bad) { m.emissive.setHex(C.amber); m.emissiveIntensity = 0.6; }
      else if (act) { m.emissive.setHex(C.cyan); m.emissiveIntensity = 0.9 + 0.9 * Math.sin(now * 4); }
      else m.emissiveIntensity = 0;
    }
    R.shimmer.material.uniforms.t.value = now;
    if (R.flow) {
      const m4 = new THREE.Matrix4(), n = R.flow.im.count;
      for (let i = 0; i < n; i++) { const p = R.flow.curve.getPointAt((i / n + now * 0.22) % 1); m4.makeTranslation(p.x, p.y, p.z); R.flow.im.setMatrixAt(i, m4); }
      R.flow.im.instanceMatrix.needsUpdate = true;
    }
    /* scene flash */
    const f = Math.max(0, 1 - (now - H.flashT) / 1.1), tint = new THREE.Color(H.flashKind === "error" ? C.red : C.green);
    R.scene.background.setHex(C.bg).lerp(tint, f * 0.28); R.scene.fog.color.copy(R.scene.background);
    R.grid.material.color.setHex(0xffffff).lerp(tint, f);
    if (R.bloom) R.bloom.strength = 0.8 + f * 1.2;
    if (R.composer) R.composer.render(); else R.renderer.render(R.scene, R.camera);
  }, "frame");
}

/* ---------- fix-it animation ---------- */
function computeFixes(S, an, L, board, steps, idx, gp) {
  const out = [], B = BOARDS[board], pin = (p) => { const r = resolvePin(board, p); return r ? r.pos.clone() : null; };
  const live = (kind) => { for (const e of R.live.values()) if (e.kind === kind && e.aTgt === 1) return e; return null; };
  const ms = arr(S.mistakes).map((m) => (typeof m === "string" ? { id: m, message: m } : m)).filter((m) => m && typeof m === "object");
  arr(S.findings).forEach((f) => { if (f && f.severity === "error") ms.push(f); });
  const seen = new Set();
  ms.slice(0, 3).forEach((m) => {
    const id = String(m.id || "").toLowerCase(), key = id + "|" + arr(m.pins).join(); if (seen.has(key)) return; seen.add(key);
    const msg = String(m.message || m.title || id || "Fix this");
    const r = live("resistor"), l = live("led");
    const sigp = pin(B.sig) || L.sig.clone();
    if (/led.*(revers|flip|polar)|revers/.test(id + " " + msg.toLowerCase()) && (l || /led/.test(id))) {
      const p = l ? l.tgt.clone() : L.led.a.clone();
      out.push({ kind: "flip", at: p.add(new V3(0.5, 0, 0)), to: p.clone(), label: "Flip the LED 180: long leg toward the resistor, short leg to GND" });
    } else if (/5v|vcc|wrong.?pin|resistor_to/.test(id) || (/resistor/.test(msg.toLowerCase()) && /5v/.test(msg.toLowerCase()))) {
      const from = pin("5V") || (r ? r.tgt.clone() : L.r.a.clone());
      out.push({ kind: "move", from, to: sigp, label: "Move the resistor wire from 5V to " + B.sig });
    } else if (/gnd|ground/.test(id)) {
      out.push({ kind: "move", from: L.rail.clone(), to: pin("GND") || L.gnd.clone(), label: "Add a wire: GND pin to the ground rail" });
    } else if (/missing|no_|not_placed/.test(id) && /resistor/.test(id)) {
      out.push({ kind: "drop", from: L.r.a.clone().add(new V3(0, 6, 0)), to: L.r.a.clone(), label: "Place the resistor here, next to " + B.sig });
    } else if (/missing|no_/.test(id) && /led/.test(id)) {
      out.push({ kind: "drop", from: L.led.a.clone().add(new V3(0, 6, 0)), to: L.led.a.clone(), label: "Place the LED here" });
    } else if (/strip|row|same/.test(id)) {
      const a = r ? r.tgt.clone() : L.r.a.clone();
      out.push({ kind: "move", from: a.clone().add(new V3(0, 0, -2)), to: L.sigHole.clone(), label: "Move this part into the same strip as " + B.sig });
    } else {
      const p = arr(m.pins).map(pin).find(Boolean) || sigp;
      out.push({ kind: "move", from: p.clone().add(new V3(0, 5, 0)), to: p, label: msg });
    }
  });
  /* missing target wire for the current step */
  if (!out.length && S.twin && S.twin.scene !== "other" && !arr(S.twin.components).some((c) => c && kindOf(c) === "wire") && !arr(S.twin.nets).length) {
    const st = steps[idx], w = st && arr(st.wires)[0];
    if (w) { const f = endpointPos(w.from, L, board, gp), t = endpointPos(w.to, L, board, gp); if (f && t) out.push({ kind: "move", from: f, to: t, label: "Add this wire: " + w.from + " -> " + w.to }); }
  }
  return out;
}
function buildFixes(list) {
  clearGroup(R.gFix); R.fixes = [];
  list.forEach((f) => {
    const g = new THREE.Group(), hex = C.mag;
    const dest = f.to, src = f.from || f.at;
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.15, 32), new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthTest: false, blending: THREE.AdditiveBlending }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(dest.x, 0.2, dest.z); ring.renderOrder = 15; g.add(ring);
    let curve = null, cone = null;
    const cm = new THREE.MeshBasicMaterial({ color: hex, depthTest: false, transparent: true, toneMapped: false });
    if (f.kind === "flip") {
      cone = new THREE.Mesh(new THREE.ConeGeometry(0.4, 1, 10), cm); cone.renderOrder = 16; g.add(cone);
      const arc = new THREE.Mesh(new THREE.TorusGeometry(1.9, 0.06, 6, 40), new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.6, depthTest: false })); arc.position.set(dest.x, 1.8, dest.z); arc.rotation.x = Math.PI / 2; g.add(arc);
    } else {
      const a = src.clone().setY(Math.max(src.y, 0.4) + 0.5), b = dest.clone().setY(1.0), mid = a.clone().add(b).multiplyScalar(0.5); mid.y += 2.5 + a.distanceTo(b) * 0.15;
      curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      const ln = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)), new THREE.LineDashedMaterial({ color: hex, dashSize: 0.45, gapSize: 0.3, transparent: true, opacity: 0.85, depthTest: false })); ln.computeLineDistances(); ln.renderOrder = 15; g.add(ln);
      cone = new THREE.Mesh(new THREE.ConeGeometry(0.45, 1.1, 10), cm); cone.renderOrder = 16; g.add(cone);
    }
    const sp = sprite(f.label, hex); const lp = curve ? curve.getPoint(0.5) : dest; sp.position.set(lp.x, lp.y + 3.4, lp.z); g.add(sp);
    R.gFix.add(g); R.fixes.push({ f, curve, cone, ring, dest });
  });
}
function updateFix(now) {
  if (!R.fixes) return;
  R.fixes.forEach((x, i) => {
    const t = (now * 0.45 + i * 0.3) % 1, p = 1 + 0.35 * Math.sin(now * 5);
    x.ring.scale.setScalar(p); x.ring.material.opacity = 0.5 + 0.4 * Math.sin(now * 5);
    if (x.curve) {
      const pt = x.curve.getPoint(t), tg = x.curve.getTangent(t);
      x.cone.position.copy(pt); x.cone.quaternion.setFromUnitVectors(new V3(0, 1, 0), tg);
    } else {
      const a = t * Math.PI * 2; x.cone.position.set(x.dest.x + Math.cos(a) * 1.9, 1.8, x.dest.z + Math.sin(a) * 1.9);
      x.cone.quaternion.setFromUnitVectors(new V3(0, 1, 0), new V3(-Math.sin(a), 0, Math.cos(a)));
      x.f.at && 0;
    }
  });
}

/* ---------- toolbar / view controls ---------- */
const VIEWS = { top: [0, 46, 0.01], front: [0, 7, 40], iso: [0, 24, 38] };
function setAutoRotate(on) { safe(() => { if (R) { R.controls.autoRotate = !!on; syncTb(); } }, "autorotate"); }
function setView(v) {
  safe(() => {
    if (!R || !VIEWS[v]) return; const p = VIEWS[v];
    R.camera.position.set(p[0], p[1], p[2]); R.controls.target.set(0, 0, v === "top" ? 3 : 4); R.controls.autoRotate = false; R.controls.update(); syncTb();
  }, "view");
}
function syncTb() { if (R && R.tbPlay) { R.tbPlay.textContent = R.controls.autoRotate ? "Pause" : "Spin"; R.tbPlay.classList.toggle("on", R.controls.autoRotate); } }
function buildToolbar() {
  const d = document.createElement("div");
  d.style.cssText = "position:absolute;left:12px;bottom:12px;display:flex;gap:4px;align-items:center;z-index:3;font:11px ui-monospace,Menlo,monospace;background:rgba(3,8,16,.7);border:1px solid #0e4a60;padding:4px 6px;border-radius:6px";
  const btn = (t, fn) => { const b = document.createElement("button"); b.textContent = t; b.style.cssText = "background:#06182a;color:#9fefff;border:1px solid #19e3ff55;border-radius:4px;padding:3px 8px;font:inherit;cursor:pointer"; b.onclick = fn; d.appendChild(b); return b; };
  R.tbPlay = btn("Spin", () => setAutoRotate(!R.controls.autoRotate));
  const sl = document.createElement("input"); sl.type = "range"; sl.min = "0.2"; sl.max = "4"; sl.step = "0.1"; sl.value = "0.8"; sl.style.width = "70px"; sl.title = "rotation speed";
  sl.oninput = () => { R.controls.autoRotateSpeed = +sl.value; }; d.appendChild(sl);
  btn("Top", () => setView("top")); btn("Front", () => setView("front")); btn("Iso", () => setView("iso"));
  btn("Reset", () => { setView("iso"); R.controls.target.set(0, 0, 5); R.controls.update(); sl.value = "0.8"; R.controls.autoRotateSpeed = 0.8; });
  return d;
}

/* ---------- public API ---------- */
function mount(host) {
  safe(() => {
    if (!host) return;
    H.host = host;
    if (R) return attach();
    if (!H.loading) H.loading = init().catch((e) => { console.error("[scene3d] init failed", e); host.textContent = "3D view unavailable: " + e.message; });
  }, "mount");
}
function update(state) {
  safe(() => {
    if (!state || typeof state !== "object") return;
    const s = H.S;
    if (typeof state.board === "string") s.board = BOARDS[state.board] ? state.board : s.board;
    s.project = state.project && typeof state.project === "object" ? state.project : null;
    s.stepIndex = Number.isFinite(+state.stepIndex) ? +state.stepIndex : 0;
    s.twin = state.twin && typeof state.twin === "object" ? state.twin : null;
    s.findings = arr(state.findings); s.mistakes = arr(state.mistakes);
    let js = ""; try { js = JSON.stringify(s.twin); } catch (e) {}
    if (Number.isFinite(+state.twinAgeS) && state.twinAgeS !== null) { H.twinAt = performance.now(); H.age0 = +state.twinAgeS; }
    else if (s.twin !== H.twinRef || js !== H.twinJson) { H.twinAt = performance.now(); H.age0 = 0; }
    H.twinRef = s.twin; H.twinJson = js;
    s.eff = twinBoard(s.twin);
    applyState(false);
  }, "update");
}
function setBoard(b) { safe(() => { if (BOARDS[b]) { H.S.board = b; H.S.eff = twinBoard(H.S.twin); applyState(false); } }, "setBoard"); }
function flash(kind) { safe(() => { H.flashKind = kind === "error" ? "error" : "ok"; H.flashT = R ? performance.now() / 1000 : -9; }, "flash"); }

export const CurrentScene = { mount, update, setBoard, flash, setAutoRotate, setView };
export { mount, update, setBoard, flash, setAutoRotate, setView };
export default CurrentScene;
if (typeof window !== "undefined") window.CurrentScene = CurrentScene;
