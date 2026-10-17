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
    label: "ARDUINO NANO", cz: 14, half: 3, sig: "D13", gnd: "GND_R",
    right: ["VIN", "GND_R", "RST_R", "5V", "A7", "A6", "A5", "A4", "A3", "A2", "A1", "A0", "AREF", "3V3", "D13"],
    left: ["D1", "D0", "RST_L", "GND_L", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12"],
  },
  esp32: {
    label: "ESP32 DEVKIT", cz: 16, half: 5, sig: "D2", gnd: "GND_R",
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
    B[side].forEach((n, i) => m.set(n, new V3(i - 7, 1.0, B.cz + sgn * B.half)));
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
    sigHole: holePos(c0, "J"),
    r: { a: holePos(c0, "I"), b: holePos(c0 + 4, "I") },
    led: { a: holePos(c0 + 4, "G"), k: holePos(c0 + 5, "G") },
    gndHole: holePos(c0 + 5, "J"),
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
const kindOf = (c) => {
  const s = (String(c && c.type) + " " + String(c && c.id)).toLowerCase();
  if (/led/.test(s)) return "led";
  if (/res|ohm/.test(s)) return "resistor";
  if (/wire|jump/.test(s)) return "wire";
  return "other";
};
const matches = (fid, c) => {
  const f = norm(fid), id = norm(c.id), ty = norm(c.type);
  return f === id || f === ty || (f === "LED" && kindOf(c) === "led") || (/^RES/.test(f) && kindOf(c) === "resistor") || (f === "R" + (c.value || "") && kindOf(c) === "resistor");
};

/* ---------- electrical analysis (client-side, mirrors verifier intent) ---------- */
function analyze(st) {
  const out = { parts: {}, complete: false, stepOk: false, badPins: new Set(), loose: [], uf: null };
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
  const rs = comps.filter((c) => kindOf(c) === "resistor"), ls = comps.filter((c) => kindOf(c) === "led");
  const rRoots = (r) => terms(r).map(rootOf);
  const allR = new Set(); rs.forEach((r) => rRoots(r).forEach((x) => x && allR.add(x)));
  let goodR = null, goodL = null;
  if (hasNets) {
    rs.forEach((r) => {
      const roots = rRoots(r);
      const mem = [].concat(...roots.map((x) => (x ? members(x) : []))).filter(isPinNode);
      const wrong = mem.find((p) => p !== sig && p !== "GND");
      if (wrong) mark(r, "bad", `Resistor on ${wrong}; it belongs on ${sig}`);
      else if (!roots.includes(sigR) || !sigR) mark(r, "bad", `Resistor is not connected to ${sig}`);
      else goodR = goodR || r;
    });
    ls.forEach((l) => {
      const ts = terms(l);
      const a = ts.find((k) => slotOf(l.id, k.split(".")[1], "led") === "a"), k = ts.find((x) => slotOf(l.id, x.split(".")[1], "led") === "k");
      const aR = a && rootOf(a), kR = k && rootOf(k);
      if ((kR && allR.has(kR) && kR !== gndR) || (aR && gndR && aR === gndR)) {
        mark(l, "bad", "LED is reversed: long leg (anode) toward the resistor, short leg to GND", { flip: true });
      } else if (!kR || !gndR || kR !== gndR) mark(l, "bad", "LED cathode (short leg) is not connected to GND");
      else if (rs.length && (!aR || !allR.has(aR))) mark(l, "warn", "LED anode is not connected to the resistor");
      else if (!rs.length) mark(l, "warn", "LED has no series resistor");
      else goodL = goodL || { l, aR };
    });
    if (goodR && goodL) {
      const other = rRoots(goodR).find((x) => x && x !== sigR);
      out.complete = !!(other && other === goodL.aR && out.parts[goodL.l.id].status === "ok" && out.parts[goodR.id].status === "ok");
    }
  }
  /* findings override / augment */
  arr(st.findings).forEach((f) => {
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
const H = { host: null, ready: false, loading: null, S: { board: "nano", project: null, stepIndex: 0, twin: null, findings: [] }, sig: "", boardKey: "", flashT: -9, flashKind: "ok" };
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
function buildResistor(mode, hex, a, b, pulsers) {
  const g = new THREE.Group(), ghost = mode === "ghost", mats = [];
  const M = (h, e) => { const m = ghost ? gMat(hex, 0.6) : sMat(h, e); if (ghost) mats.push(m); return m; };
  const mid = a.clone().add(b).multiplyScalar(0.5), d = b.clone().sub(a).setY(0).normalize();
  const body = new THREE.Group(); body.position.set(mid.x, 1.3, mid.z); body.quaternion.setFromUnitVectors(new V3(0, 1, 0), d);
  body.add(new THREE.Mesh(new THREE.CapsuleGeometry(0.38, 1.6, 4, 12), M(0xd9b98a, 0.15)));
  if (!ghost) [[-0.55, 0xe02020], [-0.2, 0xe02020], [0.15, 0x7a3b10], [0.6, 0xd4af37]].forEach(([y, c]) => { const r = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.12, 12), sMat(c, 0.2)); r.position.y = y; body.add(r); });
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

/* ---------- dynamic build ---------- */
function endpointPos(raw, L, board) {
  const s = String(raw == null ? "" : raw), h = parseHole(s);
  if (h) return holePos(h.col, h.row);
  const u = norm(s);
  if (/^(GND_?RAIL|RAIL|BB[_-]?GND|-RAIL|RAIL-)$/.test(u)) return L.rail.clone();
  let m = /^(LED\w*|L\d*)[._](\w+)$/.exec(u);
  if (m) return (slotOf("", m[2], "led") === "a" ? L.led.a : L.led.k).clone();
  m = /^(R\w*)[._](\w+)$/.exec(u);
  if (m) return (slotOf("", m[2], "res") === "a" ? L.r.a : L.r.b).clone();
  const p = resolvePin(board, s);
  return p ? p.pos : null;
}
function wireColor(c, d) { return WIRE_COL[String(c || "").toLowerCase()] || d; }

function rebuildDynamic() {
  const { S } = H, board = BOARDS[S.board] ? S.board : "nano", B = BOARDS[board];
  clearGroup(R.gTarget); clearGroup(R.gObs); clearGroup(R.gLabels);
  R.pulsers = []; R.halos = []; R.activePins = new Set(); R.badPins = new Set(); R.flow = null; R.led = null;
  const L = defaultLayout(board), an = analyze(S);
  R.an = an;
  /* ---- TARGET ---- */
  const steps = arr(S.project && S.project.steps).filter((s) => s && typeof s === "object");
  const idx = steps.length ? clamp(S.stepIndex | 0, 0, steps.length - 1) : 0;
  const defW = { sig: { f: L.sig, t: L.sigHole, c: "orange" }, g1: { f: L.gndHole, t: L.rail, c: "black" }, g2: { f: L.railPin, t: L.gnd, c: "black" } };
  let wires = [], parts = new Set();
  if (!steps.length) { wires = [["sig", true], ["g1", true], ["g2", true]]; parts = new Set(["led", "resistor"]); }
  else {
    const seen = new Set();
    steps.slice(0, idx + 1).forEach((s, si) => {
      const cur = si === idx;
      arr(s.parts).forEach((p) => { const q = String(p).toLowerCase(); if (/led/.test(q)) parts.add("led"); else if (/res|ohm/.test(q)) parts.add("resistor"); });
      arr(s.wires).forEach((w, wi) => {
        if (!w) return;
        const f = endpointPos(w.from, L, board), t = endpointPos(w.to, L, board);
        if (f && t) wires.push([{ f, t, c: w.color }, cur]);
        else {
          const key = [norm(w.from), norm(w.to)].join();
          const touchesSig = [w.from, w.to].some((x) => norm(x) === B.sig || norm(x) === "GPIO2" && board === "esp32");
          const ids = touchesSig ? ["sig"] : ["g1", "g2"];
          ids.forEach((id) => { if (!seen.has(id)) { seen.add(id); wires.push([id, cur]); } });
        }
      });
      if (cur) arr(s.pins).forEach((p) => { const r = resolvePin(board, p); if (r) R.activePins.add(r.name); });
    });
  }
  const P = (cur) => ({ list: R.pulsers, cur });
  wires.forEach(([w, cur]) => {
    const d = typeof w === "string" ? defW[w] : w;
    R.gTarget.add(buildWire("ghost", C.cyan, d.f, d.t, P(cur)));
  });
  if (parts.has("resistor")) R.gTarget.add(buildResistor("ghost", C.cyan, L.r.a, L.r.b, P(true)));
  if (parts.has("led")) R.gTarget.add(buildLED("ghost", C.cyan, L.led.a, L.led.k, false, P(true)));
  if (!steps.length) R.activePins.add(B.sig), R.activePins.add(B.gnd);
  an.badPins.forEach((p) => { const r = resolvePin(board, p); if (r) R.badPins.add(r.name); });

  /* ---- OBSERVED ---- */
  const tw = S.twin;
  if (tw && Array.isArray(tw.components)) {
    const comps = tw.components.filter((c) => c && c.id != null);
    const placeOf = (id) => { const p = arr(tw.placements).find((x) => x && norm(x.id) === norm(id)); return p ? parseHole(p.hole) : null; };
    const legs = {};
    let ri = 0, li = 0;
    const statCol = (st, def) => (st === "bad" ? C.red : st === "warn" ? C.amber : def);
    const labelAt = (pos, msg, hex) => { const s = sprite("! " + msg, hex); s.position.set(pos.x, pos.y + 3.2, pos.z); R.gLabels.add(s); };
    const halo = (pos, rad, hex) => { const h = new THREE.Mesh(new THREE.SphereGeometry(rad, 16, 12), new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, depthWrite: false })); h.position.copy(pos); R.gObs.add(h); R.halos.push(h); };
    comps.filter((c) => kindOf(c) !== "wire").forEach((c) => {
      const kind = kindOf(c), info = an.parts[c.id] || { status: "ok" }, ph = placeOf(c.id);
      const hex = statCol(info.status, C.white);
      let g;
      if (kind === "resistor") {
        const o = ri++ * 0.0, a = ph && ph.col <= 26 ? holePos(ph.col, ph.row) : L.r.a, b = ph && ph.col <= 26 ? holePos(ph.col + 4, ph.row) : L.r.b;
        g = buildResistor("solid", hex, a.clone().setZ(a.z - o), b.clone().setZ(b.z - o), null);
        legs[norm(c.id)] = { a, b };
      } else if (kind === "led") {
        const o = li++;
        const a = ph && ph.col <= 29 ? holePos(ph.col, ph.row) : L.led.a, k = ph && ph.col <= 29 ? holePos(ph.col + 1, ph.row) : L.led.k;
        g = buildLED("solid", info.status === "ok" ? 0x9fe9ff : hex, a, k, !!info.flip, null);
        legs[norm(c.id)] = info.flip ? { a: k, k: a } : { a, k };
        if (o === 0) R.led = g.userData.dome;
      } else return;
      R.gObs.add(g);
      if (info.status !== "ok") { halo(g.userData.center, kind === "led" ? 1.8 : 2.3, hex); labelAt(g.userData.center, info.msg || "Check this part", hex); }
    });
    /* wires */
    const nodeIndex = new Map();
    arr(tw.nets).filter(Array.isArray).forEach((n) => n.forEach((k) => nodeIndex.set(norm(k), n)));
    const resolveNode = (k) => {
      const u = norm(k), m = /^(.+?)\.(.+)$/.exec(u);
      if (m) { const lg = legs[m[1]]; if (lg) { const c = comps.find((x) => norm(x.id) === m[1]); return lg[slotOf(m[1], m[2], kindOf(c))] || null; } return null; }
      const p = resolvePin(board, k); if (p) return p.pos;
      const h = parseHole(k); return h ? holePos(h.col, h.row) : null;
    };
    const ends = (w) => [...nodeIndex.keys()].length ? ["a", "b", "1", "2"].map((t) => {
      const net = nodeIndex.get(norm(w.id) + "." + t.toUpperCase()); if (!net) return null;
      for (const k of net) { if (norm(k).startsWith(norm(w.id) + ".")) continue; const p = resolveNode(k); if (p) return p; }
      return null;
    }).filter(Boolean) : [];
    comps.filter((c) => kindOf(c) === "wire").forEach((w) => {
      const e = ends(w); if (e.length < 2) return;
      const info = an.parts[w.id] || { status: "ok" }, hex = info.status === "ok" ? wireColor(w.color, 0xff8a1f) : statCol(info.status);
      const g = buildWire("solid", hex, e[0], e[1], null); R.gObs.add(g);
      if (info.status !== "ok") { halo(g.userData.center, 1.6, hex); labelAt(g.userData.center, info.msg || "Check this wire", hex); }
    });
    /* flow path when complete */
    if (an.complete) {
      const rl = legs[norm((comps.find((c) => kindOf(c) === "resistor" && (an.parts[c.id] || {}).status === "ok") || {}).id)] || { a: L.r.a, b: L.r.b };
      const ll = legs[norm((comps.find((c) => kindOf(c) === "led") || {}).id)] || { a: L.led.a, k: L.led.k };
      const up = (p, y) => new V3(p.x, y, p.z);
      const pts = [L.sig, up(L.sig, 2.5), up(rl.a, 2.0), up(rl.a, 1.0), up(rl.b, 1.2), up(ll.a, 1.0), up(ll.k, 1.0), up(L.gndHole, 1.0), up(L.rail, 1.0), up(L.railPin, 1.0), L.gnd.clone()];
      const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal");
      const im = new THREE.InstancedMesh(new THREE.SphereGeometry(0.17, 8, 8), new THREE.MeshBasicMaterial({ color: C.green, blending: THREE.AdditiveBlending, transparent: true, toneMapped: false }), 44);
      R.gObs.add(im); R.flow = { im, curve };
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 160, 0.05, 5), new THREE.MeshBasicMaterial({ color: C.green, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
      R.gObs.add(tube);
    }
  }
  /* findings without a part: label at pin / above board */
  an.loose.slice(0, 3).forEach((l, i) => {
    const hex = l.sev === "bad" ? C.red : C.amber, p = l.pins.map((x) => resolvePin(board, x)).find(Boolean);
    const s = sprite("! " + l.message, hex); const base = p ? p.pos : new V3(0, 0, -9);
    s.position.set(base.x, base.y + 3.5 + (p ? 0 : i * 2.2), base.z); R.gLabels.add(s);
  });
  /* step-ok shimmer */
  R.shimmer.visible = an.stepOk;
  R.shimmer.material.uniforms.c.value.set(an.complete ? C.green : C.green);
  updateHud(steps, idx, an);
}
function updateHud(steps, idx, an) {
  if (!R.hud) return;
  const parts = Object.values(an.parts), bad = parts.filter((p) => p.status === "bad").length + an.loose.filter((l) => l.sev === "bad").length;
  const st = steps[idx] ? `STEP ${idx + 1}/${steps.length}${steps[idx].title ? " · " + steps[idx].title : ""}` : "BLINK · TARGET";
  const state = !H.S.twin ? "NO TWIN" : an.complete ? "CIRCUIT COMPLETE" : bad ? bad + " ERROR" + (bad > 1 ? "S" : "") : an.stepOk ? "STEP OK" : "BUILDING";
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
  const gStatic = new THREE.Group(), gBoard = new THREE.Group(), gTarget = new THREE.Group(), gObs = new THREE.Group(), gLabels = new THREE.Group();
  gStatic.add(buildBreadboard());
  scene.add(gStatic, gBoard, gTarget, gObs, gLabels);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 5); controls.enableDamping = true; controls.autoRotate = true; controls.autoRotateSpeed = 0.7; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 12; controls.maxDistance = 90;
  controls.addEventListener("start", () => { controls.autoRotate = false; });
  let composer = null, bloom = null;
  if (EffectComposer) safe(() => {
    composer = new EffectComposer(renderer); composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.8, 0.55, 0.3); composer.addPass(bloom); composer.addPass(new OutputPass());
  }, "bloom");
  R = { renderer, scene, camera, controls, composer, bloom, gBoard, gTarget, gObs, gLabels, shimmer, grid, ledLight, pulsers: [], halos: [], activePins: new Set(), badPins: new Set(), flow: null, led: null, an: null, clock: new THREE.Clock(), pinMeshes: {}, hud: null, ro: null };
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
  if (!R.hud) { R.hud = document.createElement("div"); R.hud.style.cssText = "position:absolute;left:10px;top:8px;font:11px/1.5 ui-monospace,Menlo,monospace;letter-spacing:.08em;pointer-events:none;text-shadow:0 0 8px #000;z-index:2"; }
  if (R.hud.parentNode !== host) host.appendChild(R.hud);
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
    if (force || H.boardKey !== H.S.board) {
      const key = BOARDS[H.S.board] ? H.S.board : "nano"; H.boardKey = H.S.board;
      clearGroup(R.gBoard); const b = buildBoard(key); R.gBoard.add(b); R.pinMeshes = b.userData.pinMeshes; H.sig = "";
    }
    const sig = JSON.stringify([H.S.board, H.S.project, H.S.stepIndex, H.S.twin, H.S.findings]);
    if (sig !== H.sig) { H.sig = sig; rebuildDynamic(); }
  }, "apply");
}
function loop() {
  requestAnimationFrame(loop);
  safe(() => {
    const now = R.clock.getElapsedTime();
    R.controls.update();
    R.pulsers.forEach((p) => { const o = p.base * (p.cur ? 0.6 + 0.4 * Math.sin(now * 3 + p.ph) : 0.45); p.mats.forEach((m) => (m.opacity = o)); });
    R.halos.forEach((h, i) => { const s = 1 + 0.22 * Math.sin(now * 5 + i); h.scale.setScalar(s); h.material.opacity = 0.25 + 0.15 * Math.sin(now * 5 + i); });
    const pm = R.pinMeshes;
    for (const n in pm) {
      const m = pm[n].material, bad = R.badPins.has(n), act = R.activePins.has(n);
      if (bad) { m.emissive.setHex(C.red); m.emissiveIntensity = 1 + Math.sin(now * 8); }
      else if (act) { m.emissive.setHex(C.cyan); m.emissiveIntensity = 0.9 + 0.9 * Math.sin(now * 4); }
      else m.emissiveIntensity = 0;
    }
    R.shimmer.material.uniforms.t.value = now;
    const on = R.an && R.an.complete && (now % 1) < 0.5;
    if (R.led) { R.led.emissive.setHex(R.an.complete ? C.green : 0x9fe9ff); R.led.color.setHex(R.an.complete && on ? 0xbfffd8 : 0x9fe9ff); R.led.emissiveIntensity = R.an.complete ? (on ? 3.5 : 0.15) : 0.2; }
    R.ledLight.intensity = R.an && R.an.complete && on ? 40 : 0;
    if (R.led && R.gObs.children.length) { const lg = R.gObs.children.find((c) => c.userData && c.userData.dome === R.led); if (lg) R.ledLight.position.copy(lg.userData.center).setY(3); }
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
    s.findings = arr(state.findings);
    applyState(false);
  }, "update");
}
function setBoard(b) { safe(() => { if (BOARDS[b]) { H.S.board = b; applyState(false); } }, "setBoard"); }
function flash(kind) { safe(() => { H.flashKind = kind === "error" ? "error" : "ok"; H.flashT = R ? R.clock.getElapsedTime() : -9; }, "flash"); }

export const CurrentScene = { mount, update, setBoard, flash };
export { mount, update, setBoard, flash };
export default CurrentScene;
if (typeof window !== "undefined") window.CurrentScene = CurrentScene;
