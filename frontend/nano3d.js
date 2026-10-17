/**
 * Technically correct Arduino Nano (ATmega328) pinout visualization.
 * USB at +Z (“up”). Pin order matches common Nano clone silkscreen.
 * Blink target: D13 → 220Ω → LED anode; LED cathode → GND (right-edge GND near D13).
 */
(function () {
  const canvasHost = document.getElementById("nano3d");
  if (!canvasHost || !window.THREE) return;

  const THREE = window.THREE;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0c0e10);

  const w = canvasHost.clientWidth || 320;
  const h = canvasHost.clientHeight || 280;
  const camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 100);
  camera.position.set(0, 9, 14);
  camera.lookAt(0, 0, 0);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h);
  canvasHost.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 0.85);
  key.position.set(4, 10, 6);
  scene.add(key);

  const board = new THREE.Group();
  scene.add(board);

  const pcb = new THREE.Mesh(
    new THREE.BoxGeometry(4.2, 0.12, 9.0),
    new THREE.MeshStandardMaterial({ color: 0x1a4a8a, metalness: 0.2, roughness: 0.65 })
  );
  board.add(pcb);

  const usb = new THREE.Mesh(
    new THREE.BoxGeometry(1.4, 0.45, 1.1),
    new THREE.MeshStandardMaterial({ color: 0xb0b6be, metalness: 0.7, roughness: 0.35 })
  );
  usb.position.set(0, 0.28, 4.2);
  board.add(usb);

  const xtal = new THREE.Mesh(
    new THREE.BoxGeometry(0.7, 0.25, 0.45),
    new THREE.MeshStandardMaterial({ color: 0xd8dde4, metalness: 0.5, roughness: 0.4 })
  );
  xtal.position.set(-0.9, 0.2, 1.2);
  board.add(xtal);

  const builtin = new THREE.Mesh(
    new THREE.BoxGeometry(0.25, 0.12, 0.35),
    new THREE.MeshStandardMaterial({ color: 0x222222, emissive: 0x000000 })
  );
  builtin.position.set(1.35, 0.14, -3.4);
  board.add(builtin);

  /**
   * Left edge (−X), USB top → bottom:
   *   D1/TX, D0/RX, RESET, GND, D2…D12
   * Right edge (+X), USB top → bottom:
   *   VIN, GND, RESET, 5V, A7…A0, AREF, 3V3, D13
   */
  const LEFT = [
    "D1", "D0", "RST_L", "GND_L", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12",
  ];
  const RIGHT = [
    "VIN", "GND_R", "RST_R", "5V", "A7", "A6", "A5", "A4", "A3", "A2", "A1", "A0", "AREF", "3V3", "D13",
  ];

  const pinMeshes = {};
  const pinMat = new THREE.MeshStandardMaterial({ color: 0xc0c4cc, metalness: 0.8, roughness: 0.3 });
  const hiMat = new THREE.MeshStandardMaterial({
    color: 0xd6ff4b,
    emissive: 0x6a8a20,
    emissiveIntensity: 0.7,
    metalness: 0.4,
    roughness: 0.35,
  });

  function makePin(name, x, z) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.55, 0.28), pinMat.clone());
    m.position.set(x, 0.28, z);
    m.userData.name = name;
    board.add(m);
    pinMeshes[name] = m;
    return m;
  }

  const zTop = 3.5;
  const zStep = 0.5;
  LEFT.forEach((name, i) => makePin(name, -2.0, zTop - i * zStep));
  RIGHT.forEach((name, i) => makePin(name, 2.0, zTop - i * zStep));

  const bread = new THREE.Mesh(
    new THREE.BoxGeometry(7.5, 0.15, 4.5),
    new THREE.MeshStandardMaterial({ color: 0xf2efe8, roughness: 0.9 })
  );
  bread.position.set(0, -0.55, -1.5);
  scene.add(bread);

  const led = new THREE.Mesh(
    new THREE.CylinderGeometry(0.22, 0.22, 0.55, 12),
    new THREE.MeshStandardMaterial({ color: 0xe4574a, emissive: 0x401010, transparent: true, opacity: 0.15 })
  );
  led.position.set(-1.2, -0.15, -2.4);
  scene.add(led);

  const resistor = new THREE.Mesh(
    new THREE.CylinderGeometry(0.12, 0.12, 1.1, 10),
    new THREE.MeshStandardMaterial({ color: 0xc87941, transparent: true, opacity: 0.15 })
  );
  resistor.rotation.z = Math.PI / 2;
  resistor.position.set(0.2, -0.15, -2.4);
  scene.add(resistor);

  const wireGroup = new THREE.Group();
  scene.add(wireGroup);

  function clearWires() {
    while (wireGroup.children.length) {
      const c = wireGroup.children.pop();
      if (c.geometry) c.geometry.dispose();
    }
  }

  function addWire(a, b, color) {
    const curve = new THREE.CatmullRomCurve3([
      a.clone(),
      new THREE.Vector3((a.x + b.x) / 2, Math.max(a.y, b.y) + 0.8, (a.z + b.z) / 2),
      b.clone(),
    ]);
    const geom = new THREE.TubeGeometry(curve, 24, 0.05, 6, false);
    const mesh = new THREE.Mesh(
      geom,
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25 })
    );
    wireGroup.add(mesh);
  }

  function worldPin(name) {
    const alias = name === "GND" ? "GND_R" : name === "RST" ? "RST_R" : name;
    const m = pinMeshes[alias] || pinMeshes[name];
    if (!m) return new THREE.Vector3(0, 0, 0);
    const v = new THREE.Vector3();
    m.getWorldPosition(v);
    return v;
  }

  let pulse = 0;
  let activePins = [];
  let stepId = "orient";

  function resolvePinNames(pins) {
    return (pins || []).flatMap((p) => {
      if (p === "GND") return ["GND_R", "GND_L"];
      if (p === "RST") return ["RST_R"];
      return [p];
    });
  }

  function parseColor(c) {
    if (typeof c === "number") return c;
    if (typeof c === "string" && c.startsWith("#")) return parseInt(c.slice(1), 16);
    return 0xd6ff4b;
  }

  function setStep(step) {
    if (!step) return;
    stepId = step.id || "orient";
    activePins = resolvePinNames(step.pins || []);
    Object.values(pinMeshes).forEach((m) => {
      m.material = pinMat.clone();
      m.scale.set(1, 1, 1);
    });
    activePins.forEach((name) => {
      const m = pinMeshes[name];
      if (m) m.material = hiMat.clone();
    });

    const opac = {
      orient: { led: 0.1, r: 0.1 },
      led: { led: 1, r: 0.15 },
      resistor: { led: 1, r: 1 },
      gnd: { led: 1, r: 1 },
      flash: { led: 1, r: 1 },
    }[stepId] || { led: 0.2, r: 0.2 };
    led.material.opacity = opac.led;
    resistor.material.opacity = opac.r;
    led.material.emissive.setHex(stepId === "flash" ? 0xaa2020 : 0x401010);

    clearWires();
    const pts = {
      D13: () => worldPin("D13"),
      GND: () => worldPin("GND_R"),
      GND_R: () => worldPin("GND_R"),
      GND_L: () => worldPin("GND_L"),
      "R220.a": () => resistor.position.clone().add(new THREE.Vector3(-0.55, 0.1, 0)),
      "R220.b": () => resistor.position.clone().add(new THREE.Vector3(0.55, 0.1, 0)),
      "LED.a": () => led.position.clone().add(new THREE.Vector3(0, 0.2, 0.25)),
      "LED.k": () => led.position.clone().add(new THREE.Vector3(0, 0.2, -0.25)),
    };
    (step.wires || []).forEach((w) => {
      const a = (pts[w.from] || (() => worldPin(w.from)))();
      const b = (pts[w.to] || (() => worldPin(w.to)))();
      addWire(a, b, parseColor(w.color));
    });
  }

  window.CURRENT_NANO3D = { setStep, pinMeshes };

  function onResize() {
    const ww = canvasHost.clientWidth || 320;
    const hh = canvasHost.clientHeight || 280;
    camera.aspect = ww / hh;
    camera.updateProjectionMatrix();
    renderer.setSize(ww, hh);
  }
  window.addEventListener("resize", onResize);

  function animate() {
    requestAnimationFrame(animate);
    pulse += 0.04;
    board.rotation.y = Math.sin(pulse * 0.25) * 0.12;
    activePins.forEach((name) => {
      const m = pinMeshes[name];
      if (!m) return;
      const s = 1 + Math.sin(pulse * 3) * 0.08;
      m.scale.set(s, s, s);
    });
    if (stepId === "flash") {
      const on = Math.sin(pulse * 2) > 0;
      led.material.emissive.setHex(on ? 0xff3030 : 0x200808);
      builtin.material.emissive = new THREE.Color(on ? 0xffaa33 : 0x000000);
    }
    renderer.render(scene, camera);
  }
  animate();
  setStep({ id: "orient", pins: ["D13", "GND"], wires: [] });
})();
