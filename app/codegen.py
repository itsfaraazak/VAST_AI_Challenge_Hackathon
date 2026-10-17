"""Teaching-tone Arduino/ESP32 sketch generation grounded in the live project + twin.

LLM (W&B Llama via coach._llm) first, deterministic validator, deterministic fallback templates.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from pathlib import Path

NANO_PINS = {f"D{i}": i for i in range(2, 14)} | {f"A{i}": 14 + i for i in range(6)}
NANO_PWM = {3, 5, 6, 9, 10, 11}
NANO_DIGITAL = set(range(2, 14)) | set(range(14, 20))  # D2..D13, A0..A5 as digital 14..19
ESP_BAD = set(range(6, 12))  # GPIO6-11 are wired to the SPI flash
ESP_INPUT_ONLY = {34, 35, 36, 39}
MAX_LINES = 60
DEFAULT_PIN = {"nano": 13, "esp32": 2}
FQBN = {"nano": "arduino:avr:nano", "esp32": "esp32:esp32:esp32"}


def _board(b) -> str:
    return "esp32" if "esp" in str(b or "").lower() else "nano"


def pin_num(ep, board: str) -> int | None:
    """'D5'->5, 'A0'->14, 'GPIO25'->25; None if not a signal pin."""
    u = str(ep or "").upper().strip()
    if "." in u:
        return None
    if board == "nano":
        return NANO_PINS.get(u)
    m = re.match(r"^(?:GPIO|IO|D)(\d{1,2})$", u)
    return int(m.group(1)) if m else None


def valid_pin(n: int, board: str, output: bool = True) -> bool:
    if board == "nano":
        return n in NANO_DIGITAL
    if n < 0 or n > 39 or n in ESP_BAD:
        return False
    return not (output and n in ESP_INPUT_ONLY)


def pin_label(n: int, board: str) -> str:
    if board == "esp32":
        return f"GPIO{n}"
    return f"A{n - 14}" if n >= 14 else f"D{n}"


# ---------------------------------------------------------------- twin / project context
def context(sess) -> dict:
    import coach as C
    import projects_store as PS
    c = sess.coach or {}
    board = _board(c.get("board"))
    project = C._project(sess) if c.get("project_id") else None
    idx = int(c.get("step_index") or 0)
    wired, ptypes, has_res = [], set(), False
    if project:
        for s in project.get("steps", [])[: idx + 1]:
            for w in s.get("wires") or []:
                for ep in (w.get("from"), w.get("to")):
                    n = pin_num(ep, board)
                    if n is not None and n not in wired:
                        wired.append(n)
                    if str(ep or "").upper().startswith("R"):
                        has_res = True
        for p in project.get("parts_list") or []:
            ptypes.add(str(p.get("type", "")).lower())
    seen = PS.parts_seen(sess)
    if "resistor" in seen:
        has_res = True
    parts = ptypes | set(seen)
    return {"board": board, "project": project, "step_index": idx, "pins": wired, "parts_seen": seen,
            "parts": sorted(parts), "has_resistor": has_res or "resistor" in ptypes and idx >= 2}


# ---------------------------------------------------------------- templates
def _kind(ctx: dict, instruction: str | None) -> str:
    i = (instruction or "").lower()
    if re.search(r"fade|pulse|breath|dim", i):
        return "fade"
    if re.search(r"button|toggle|press|switch", i):
        return "button-led"
    if re.search(r"buzz|beep|tone|sound", i):
        return "buzzer"
    if i and re.search(r"blink|fast|slow|flash", i):
        return "blink"
    p = ctx.get("project") or {}
    blob = (str(p.get("id", "")) + " " + str(p.get("title", "")) + " " + " ".join(ctx.get("parts", []))).lower()
    if "buzz" in blob:
        return "buzzer"
    if "fade" in blob or "pwm" in blob:
        return "fade"
    if "button" in blob:
        return "button-led"
    return "blink"


def _params(ctx: dict, instruction: str | None) -> tuple[int, int, int | None]:
    board = ctx["board"]
    i = (instruction or "").lower()
    pin = ctx["pins"][0] if ctx["pins"] else DEFAULT_PIN[board]
    m = re.search(r"(?:pin|gpio|d)\s*#?(\d{1,2})\b", i)
    if m and valid_pin(int(m.group(1)), board):
        pin = int(m.group(1))
    delay = 1000
    if re.search(r"twice as fast|2x|double|faster|quick", i):
        delay = 500
    if re.search(r"slower|half as fast|twice as slow", i):
        delay = 2000
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ms|s|sec)", i)
    if m:
        delay = int(float(m.group(1)) * (1 if m.group(2) == "ms" else 1000))
    delay = max(20, min(5000, delay))
    btn = None
    if len(ctx["pins"]) > 1:
        btn = ctx["pins"][1]
    else:
        btn = 4 if board == "nano" else 4
    if btn == pin:
        btn = 7 if board == "nano" else 5
    return pin, delay, btn


def fallback_sketch(ctx: dict, instruction: str | None = None) -> str:
    board = ctx["board"]
    kind = _kind(ctx, instruction)
    pin, d, btn = _params(ctx, instruction)
    lab = pin_label(pin, board)
    if kind == "fade" and board == "nano" and pin not in NANO_PWM:
        pin = 9
        lab = "D9"
    if kind == "blink":
        return f"""// Blink {lab}: the "hello world" of hardware.
const int LED_PIN = {pin};   // the pin your resistor + LED hang off
const int HALF_PERIOD = {d};  // ms on, then ms off

void setup() {{
  // Pins default to INPUT; we must say OUTPUT so it can drive current.
  pinMode(LED_PIN, OUTPUT);
}}

void loop() {{
  digitalWrite(LED_PIN, HIGH);  // {'3.3' if board == 'esp32' else '5'} V out: LED on
  delay(HALF_PERIOD);           // delay() just waits; fine for a demo
  digitalWrite(LED_PIN, LOW);   // 0 V: LED off
  delay(HALF_PERIOD);
}}
"""
    if kind == "fade":
        if board == "nano":
            return f"""// Fade {lab} with PWM. Only ~-pins (3,5,6,9,10,11) can do analogWrite.
const int LED_PIN = {pin};
int level = 0;   // 0..255 brightness
int stepBy = 5;  // how fast it ramps

void setup() {{
  pinMode(LED_PIN, OUTPUT);
}}

void loop() {{
  analogWrite(LED_PIN, level);  // PWM: rapid on/off, duty = brightness
  level += stepBy;
  if (level <= 0 || level >= 255) stepBy = -stepBy;  // bounce at the ends
  delay(20);                    // 20 ms/step -> smooth to the eye
}}
"""
        return f"""// Fade {lab} with PWM on the ESP32 (Arduino-ESP32 core 3.x LEDC API).
const int LED_PIN = {pin};
int level = 0;   // 0..255 brightness (8-bit)
int stepBy = 5;

void setup() {{
  // ESP32 has no fixed PWM pins: LEDC lets any output pin do PWM.
  ledcAttach(LED_PIN, 5000, 8);  // 5 kHz is flicker-free, 8 bits = 0..255
}}

void loop() {{
  ledcWrite(LED_PIN, level);     // duty cycle = brightness
  level += stepBy;
  if (level <= 0 || level >= 255) stepBy = -stepBy;
  delay(20);
}}
"""
    if kind == "button-led":
        hi = "3.3" if board == "esp32" else "5"
        return f"""// Button toggles the LED on {lab}. Button on pin {btn} to GND.
const int LED_PIN = {pin};
const int BTN_PIN = {btn};
bool ledOn = false;
bool lastPressed = false;

void setup() {{
  pinMode(LED_PIN, OUTPUT);
  // INPUT_PULLUP uses the chip's internal resistor, so no extra part;
  // the pin reads HIGH ({hi} V) until the button pulls it to GND.
  pinMode(BTN_PIN, INPUT_PULLUP);
}}

void loop() {{
  bool pressed = (digitalRead(BTN_PIN) == LOW);
  if (pressed && !lastPressed) {{   // act only on the press edge
    ledOn = !ledOn;
    digitalWrite(LED_PIN, ledOn ? HIGH : LOW);
    delay(30);                      // debounce: contacts bounce for ~ms
  }}
  lastPressed = pressed;
}}
"""
    # buzzer
    return f"""// Beep a piezo buzzer on {lab} (buzzer + to pin, - to GND).
const int BUZZ_PIN = {pin};

void setup() {{
  pinMode(BUZZ_PIN, OUTPUT);
}}

void loop() {{
  // tone() square-waves the pin at 440 Hz (concert A). Passive buzzers need this.
  tone(BUZZ_PIN, 440, 200);
  delay({max(300, d // 2)});  // gap between beeps so you hear each one
}}
"""


# ---------------------------------------------------------------- validator
def validate(code: str, board: str, has_resistor: bool = True) -> tuple[bool, list[str], list[str]]:
    """-> (ok, problems, notes). Problems block acceptance, notes are advisory."""
    probs, notes = [], []
    if not code or not code.strip():
        return False, ["empty"], notes
    stripped = re.sub(r"//[^\n]*|/\*.*?\*/", "", code, flags=re.S)
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', stripped)
    if stripped.count("{") != stripped.count("}") or stripped.count("(") != stripped.count(")"):
        probs.append("unbalanced braces or parentheses")
    if not re.search(r"\bvoid\s+setup\s*\(\s*(?:void)?\s*\)\s*\{", stripped):
        probs.append("missing setup()")
    if not re.search(r"\bvoid\s+loop\s*\(\s*(?:void)?\s*\)\s*\{", stripped):
        probs.append("missing loop()")
    if len(code.strip().splitlines()) > MAX_LINES:
        probs.append(f"more than {MAX_LINES} lines")
    consts = {m.group(1): int(m.group(2)) for m in
              re.finditer(r"\b(?:const\s+)?(?:int|byte|uint8_t|#define)\s+(\w+)\s*=?\s*(\d+)\s*;?", stripped)}
    consts |= {m.group(1): int(m.group(2)) for m in re.finditer(r"#define\s+(\w+)\s+(\d+)", stripped)}
    out_pins = set()
    for m in re.finditer(r"\b(pinMode|digitalWrite|analogWrite|ledcAttach|ledcWrite|tone)\s*\(\s*([A-Za-z_]\w*|\d+)", stripped):
        fn, arg = m.group(1), m.group(2)
        n = int(arg) if arg.isdigit() else consts.get(arg)
        if n is None:
            # allow A0.. / LED_BUILTIN / loop vars silently
            continue
        is_out = fn != "pinMode" or "OUTPUT" in stripped[m.end():m.end() + 40]
        if not valid_pin(n, board, output=is_out):
            probs.append(f"pin {n} is not usable as output on {board}")
        elif fn != "pinMode" or is_out:
            out_pins.add(n)
    if board == "nano":
        if re.search(r"\bledc\w*\(", stripped):
            probs.append("LEDC is ESP32-only; use analogWrite on a ~PWM pin")
        for m in re.finditer(r"analogWrite\s*\(\s*(\w+)", stripped):
            n = int(m.group(1)) if m.group(1).isdigit() else consts.get(m.group(1))
            if n is not None and n not in NANO_PWM:
                probs.append(f"pin {n} has no PWM on the Nano (use 3,5,6,9,10,11)")
    for m in re.finditer(r"\bdelay\s*\(\s*(\d+)\s*\)", stripped):
        if not (1 <= int(m.group(1)) <= 10000):
            probs.append(f"delay({m.group(1)}) outside 1..10000 ms")
    for name, v in consts.items():
        if "DELAY" in name.upper() or "PERIOD" in name.upper():
            if not (1 <= v <= 10000):
                probs.append(f"{name}={v} outside 1..10000 ms")
    if out_pins and not has_resistor:
        notes.append("No series resistor seen yet: add ~220 ohm in line with the LED before uploading, or the pin and LED can burn out.")
    return (not probs), probs, notes


def compile_check(code: str, board: str, timeout: float = 40.0) -> tuple[bool | None, str]:
    """arduino-cli compile; None = unavailable/skipped."""
    exe = shutil.which("arduino-cli")
    if not exe:
        return None, ""
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        sk = Path(d) / "current_sketch"
        sk.mkdir()
        (sk / "current_sketch.ino").write_text(code)
        try:
            r = subprocess.run([exe, "compile", "--fqbn", FQBN[board], str(sk)], capture_output=True, text=True, timeout=timeout)
        except Exception:  # noqa: BLE001
            return None, ""
    out = (r.stderr or "") + (r.stdout or "")
    if r.returncode == 0:
        return True, "compiled"
    low = out.lower()
    if any(k in low for k in ("platform not installed", "unknown fqbn", "invalid fqbn", "no such core", "platform not found")):
        return None, ""  # core missing: skip silently
    lines = [ln for ln in out.strip().splitlines() if "error" in ln.lower()]
    return False, (lines[0] if lines else "compile failed")[:160]


# ---------------------------------------------------------------- LLM
SYSTEM = (
    "You write tiny, correct Arduino sketches for a beginner learning electronics on a breadboard. "
    "Reply with ONE complete .ino in a ```cpp fenced block and nothing else. Max 55 lines. Must define "
    "void setup() and void loop(). Comment WHY each line matters in a friendly teaching tone. "
    "Use ONLY the pins listed as wired. Nano: pinMode/digitalWrite/analogWrite (PWM only on 3,5,6,9,10,11). "
    "ESP32: GPIO numbers, ledcAttach(pin,freq,bits)+ledcWrite(pin,duty) for PWM (no analogWrite), 3.3 V logic, "
    "never GPIO6-11. Keep delay() values between 10 and 5000 ms."
)


def _extract(text: str) -> str:
    m = re.search(r"```(?:cpp|c\+\+|arduino|ino|c)?\s*\n(.*?)```", text or "", re.S)
    return (m.group(1) if m else (text or "")).strip() + "\n"


def describe(ctx: dict) -> str:
    p = ctx.get("project") or {}
    steps = [f"{i + 1}. {s.get('title')} wires={[(w.get('from'), w.get('to')) for w in s.get('wires') or []][:6]}"
             for i, s in enumerate((p.get("steps") or [])[: ctx['step_index'] + 1])]
    return (f"Board: {ctx['board']}\nProject: {p.get('title', 'none yet')} - {p.get('pitch', '')}\n"
            f"Parts seen on the bench by the twin: {', '.join(ctx['parts_seen']) or 'none yet'}\n"
            f"Signal pins actually wired so far: {[pin_label(n, ctx['board']) for n in ctx['pins']] or 'none yet'}\n"
            f"Series resistor present: {ctx['has_resistor']}\nBuild steps so far:\n" + "\n".join(steps))


async def generate_sketch(sess, http, instruction: str | None = None, compile: bool = False) -> dict:
    import coach as C
    C.ensure_session_coach(sess)
    ctx = context(sess)
    board = ctx["board"]
    prev = sess.coach.get("sketch_current")
    user = describe(ctx)
    if prev:
        user += f"\nCurrent sketch:\n```cpp\n{prev['code']}```"
    user += f"\nInstruction: {instruction or 'write the sketch for this project as it is wired'}"
    notes, source, code = [], "wandb", ""
    try:
        text, _meta = await C._llm(sess, http, SYSTEM, user, max_tokens=900)
        code = _extract(text) if text else ""
    except Exception:  # noqa: BLE001
        code = ""
    ok, probs, advis = validate(code, board, ctx["has_resistor"]) if code.strip() else (False, ["no LLM output"], [])
    if ok and compile:
        cok, cmsg = await asyncio.to_thread(compile_check, code, board)
        if cok is False:
            ok, probs = False, [f"compile: {cmsg}"]
        elif cok:
            notes.append("Compile check passed (arduino-cli).")
    if not ok:
        source = "template"
        notes.append("Used a built-in template (" + "; ".join(probs)[:120] + ").")
        code = fallback_sketch(ctx, instruction)
        _, _, advis = validate(code, board, ctx["has_resistor"])
    notes += advis
    hist = sess.coach.setdefault("sketch_history", [])
    if prev:
        hist.append(prev)
        del hist[:-10]
    pins = [pin_label(n, board) for n in sorted({int(x) for x in re.findall(r"(?:LED_PIN|BTN_PIN|BUZZ_PIN)\s*=\s*(\d+)", code)})]
    res = {"code": code, "board": board, "pins": pins, "notes": notes, "source": source, "instruction": instruction or ""}
    sess.coach["sketch_current"] = {k: res[k] for k in ("code", "board", "pins", "notes")}
    _persist_sketch(sess, code)
    return res


def undo(sess) -> dict | None:
    hist = (sess.coach or {}).get("sketch_history") or []
    if not hist:
        return None
    prev = hist.pop()
    sess.coach["sketch_current"] = prev
    _persist_sketch(sess, prev["code"])
    return prev


def _persist_sketch(sess, code: str) -> None:
    try:
        import projects_store
        sess.coach["sketch_text"] = code
        projects_store.schedule_save(sess)
    except Exception:  # noqa: BLE001
        pass


def current(sess) -> dict:
    """Latest sketch, or the deterministic template if none was generated yet."""
    import coach as C
    C.ensure_session_coach(sess)
    cur = sess.coach.get("sketch_current")
    if cur:
        return cur
    ctx = context(sess)
    code = fallback_sketch(ctx)
    _, _, advis = validate(code, ctx["board"], ctx["has_resistor"])
    return {"code": code, "board": ctx["board"], "pins": [pin_label(n, ctx["board"]) for n in ctx["pins"][:1]],
            "notes": ["Starter template; ask for changes to customize."] + advis}
