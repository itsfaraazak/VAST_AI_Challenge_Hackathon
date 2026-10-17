/* Camera device picker (ported from teammate integration branch).
   Usage: CurrentCamera.populate(selectEl, onPick) -> Promise<deviceId|"">
   Prefers Desk View > Continuity Camera > iPhone/iPad > rear > built-in. */
(function () {
  function score(label) {
    var l = (label || "").toLowerCase();
    if (l.includes("desk view")) return 100;
    if (l.includes("continuity")) return 90;
    if (l.includes("iphone") || l.includes("ipad")) return 80;
    if (l.includes("back") || l.includes("rear") || l.includes("environment")) return 50;
    if (l.includes("facetime") || l.includes("integrated") || l.includes("built-in")) return 20;
    return 10;
  }
  function friendly(d, i) {
    var raw = (d.label || "").trim();
    if (!raw) return "Camera " + (i + 1);
    if (/desk view/i.test(raw)) return "Desk View — " + raw;
    if (/continuity/i.test(raw)) return "Continuity — " + raw;
    return raw;
  }
  async function list() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    var all = await navigator.mediaDevices.enumerateDevices();
    return all.filter(function (d) { return d.kind === "videoinput"; });
  }
  function preferred(devs) {
    if (!devs.length) return "";
    return devs.slice().sort(function (a, b) { return score(b.label) - score(a.label); })[0].deviceId;
  }
  async function populate(selectEl, onPick) {
    var devs = await list();
    selectEl.innerHTML = "";
    if (!devs.length) {
      var o = document.createElement("option");
      o.value = ""; o.textContent = "No cameras found";
      selectEl.appendChild(o); selectEl.disabled = true;
      return "";
    }
    var pick = preferred(devs);
    devs.forEach(function (d, i) {
      var o = document.createElement("option");
      o.value = d.deviceId; o.textContent = friendly(d, i);
      if (d.deviceId === pick) o.selected = true;
      selectEl.appendChild(o);
    });
    selectEl.disabled = false;
    selectEl.onchange = function () { if (onPick) onPick(selectEl.value); };
    return pick;
  }
  window.CurrentCamera = { populate: populate, list: list, preferred: preferred, score: score };
})();
