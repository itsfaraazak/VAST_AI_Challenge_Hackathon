/** Voice: sanitizer + sentence-queued TTS. Pure sanitizer is node-testable. */
const ONES = ["zero","one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve","thirteen","fourteen","fifteen","sixteen","seventeen","eighteen","nineteen"];
const TENS = ["","","twenty","thirty","forty","fifty","sixty","seventy","eighty","ninety"];
export function num(n) {
  n = Math.floor(+n);
  if (n < 20) return ONES[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? " " + ONES[n % 10] : "");
  if (n < 1000) return ONES[Math.floor(n / 100)] + " hundred" + (n % 100 ? " " + num(n % 100) : "");
  if (n < 1000000) return num(Math.floor(n / 1000)) + " thousand" + (n % 1000 ? " " + num(n % 1000) : "");
  return String(n);
}
/* Example: "Blink it is. D13 → 220Ω → LED anode; cathode → GND."
   => "Blink it is. pin D thirteen to two hundred twenty ohms to LED anode; cathode to ground." */
export function sanitize(t) {
  let s = String(t ?? "");
  if (/^\s*[\[{]/.test(s) || /[{}]/.test(s)) return "";
  s = s.replace(/https?:\/\/\S+/g, "").replace(/```[\s\S]*?```/g, "").replace(/`([^`]*)`/g, "$1");
  s = s.replace(/\(([^)]{41,})\)/g, "");
  s = s.replace(/[*_#>~|]+/g, "").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");
  s = s.replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, "");
  s = s.replace(/\s*(->|=>|→|⟶|—>)\s*/g, " to ");
  s = s.replace(/(\d+(?:\.\d+)?)\s*(?:k|K)\s*(?:Ω|ohms?)/g, (_, n) => num(n) + " kilo ohms");
  s = s.replace(/(\d+)\s*(?:Ω|ohms?)\b/gi, (_, n) => num(n) + " ohms");
  s = s.replace(/Ω/g, " ohms");
  s = s.replace(/\b3V3\b/gi, "three point three volts");
  s = s.replace(/\b(\d+(?:\.\d+)?)\s*V\b/g, (_, n) => (n.includes(".") ? n.replace(".", " point ") : num(n)) + (+n === 1 ? " volt" : " volts"));
  s = s.replace(/\b(\d+)\s*mA\b/g, (_, n) => num(n) + " milliamps");
  s = s.replace(/\bGND\b/g, "ground");
  s = s.replace(/\bGPIO\s?(\d+)\b/g, (_, n) => "GPIO " + num(n));
  s = s.replace(/\bD(\d{1,2})\b/g, (_, n) => "pin D " + num(n));
  s = s.replace(/\bA([0-7])\b/g, (_, n) => "A " + ONES[+n]);
  s = s.replace(/\b[A-J](\d{1,2})\b/g, (_, n) => "row " + num(n));
  s = s.replace(/(\d+)/g, (_, n) => (n.length < 7 ? num(n) : n));
  s = s.replace(/\.{2,}|…/g, ".").replace(/[(){}\[\]<>\/\\=+^]/g, " ").replace(/\s*;\s*/g, "; ");
  s = s.replace(/[^\p{L}\p{N}\s.,;:!?'’\-]/gu, " ");
  return s.replace(/\s+/g, " ").replace(/\s+([.,;:!?])/g, "$1").trim();
}
export function firstSentences(t, n = 2, max = 220) {
  const parts = String(t).match(/[^.!?]+[.!?]*/g) || [];
  let out = parts.slice(0, n).join(" ").trim();
  if (out.length > max) out = out.slice(0, max).replace(/\s\S*$/, "");
  return out;
}
export function sentences(t) { return (String(t).match(/[^.!?]+[.!?]*/g) || []).map((x) => x.trim()).filter((x) => /\p{L}/u.test(x)); }

/* ---- browser side ---- */
const GOOD = /Samantha|Ava|Allison|Google US English|Microsoft (Aria|Jenny|Guy)|Natural|Premium|Enhanced/i;
export function createVoice({ onState } = {}) {
  const synth = typeof speechSynthesis !== "undefined" ? speechSynthesis : null;
  let muted = false, unlocked = false, voices = [], chosen = null;
  try { muted = localStorage.getItem("current.muted") === "1"; chosen = localStorage.getItem("current.voice"); } catch {}
  const recent = new Map(); let cantSee = 0, active = 0;
  const state = () => onState?.({ speaking: active > 0, muted });
  function pick() {
    voices = (synth?.getVoices() || []).filter((v) => /^en/i.test(v.lang));
    voices.sort((a, b) => (GOOD.test(b.name) - GOOD.test(a.name)) || ((b.lang === "en-US") - (a.lang === "en-US")));
    return voices;
  }
  function voiceObj() { return voices.find((v) => v.name === chosen) || voices[0] || null; }
  if (synth) { pick(); synth.onvoiceschanged = () => { pick(); onState?.({ voices }); }; }
  function cancel() { try { synth?.cancel(); } catch {} active = 0; state(); }
  function speakGuidance(text, source) {
    if (muted || !unlocked || !synth) return;
    if (source && !/wandb|llm|verifier|curriculum|coach/i.test(source)) return;
    if (/can'?t see (your|the) board/i.test(text)) { if (Date.now() - cantSee < 60000) return; cantSee = Date.now(); }
    const clean = sanitize(firstSentences(text));
    if (!clean) return;
    cancel();
    const now = Date.now();
    for (const [k, v] of recent) if (now - v > 30000) recent.delete(k);
    for (const sen of sentences(clean)) {
      if (recent.has(sen)) continue;
      recent.set(sen, now);
      const u = new SpeechSynthesisUtterance(sen);
      u.rate = 1.0; u.pitch = 1.0; const v = voiceObj(); if (v) { u.voice = v; u.lang = v.lang; }
      active++; u.onend = u.onerror = () => { active = Math.max(0, active - 1); state(); };
      synth.speak(u);
    }
    state();
  }
  return {
    speakGuidance, cancel, pick, get muted() { return muted; }, get voices() { return voices; }, get chosen() { return voiceObj()?.name; },
    unlock() { unlocked = true; },
    setMuted(m) { muted = !!m; try { localStorage.setItem("current.muted", m ? "1" : "0"); } catch {} if (m) cancel(); state(); },
    setVoice(n) { chosen = n; try { localStorage.setItem("current.voice", n); } catch {} },
  };
}
