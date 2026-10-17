"""Proactive teacher: curriculum + twin + W&B conversation."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from config import settings
import curriculum
from curriculum import get_project, infer_step_from_twin, list_projects, normalize_board, step_at
from mistakes import diagnose, public as public_mistakes
from trace import span

IDLE_SECS = 20.0
HINT_GAP_SECS = 20.0

log = logging.getLogger("coach")

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore


async def _wandb_chat(http: aiohttp.ClientSession, system: str, user: str, max_tokens: int = 220,
                      timeout: int = 45, temperature: float = 0.3) -> tuple[str, dict]:
    from guidance import list_and_pick_model

    meta: dict[str, Any] = {"ms": 0, "model": None, "source": "policy"}
    model = await list_and_pick_model(http)
    if not model or not settings.wandb_ready:
        return "", meta
    meta["model"] = model
    headers = {
        "Authorization": f"Bearer {settings.wandb_key}",
        "Content-Type": "application/json",
        "OpenAI-Project": f"{settings.wandb_team}/{settings.wandb_project}",
    }
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    t0 = time.perf_counter()
    try:
        async with http.post(
            settings.wandb_base + "/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            data = await resp.json()
            meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status >= 400:
                return "", meta
            text = data["choices"][0]["message"]["content"].strip()
            meta["source"] = "wandb"
            return text, meta
    except Exception:  # noqa: BLE001
        meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return "", meta


async def _llm(sess, http, system: str, user: str, **kw) -> tuple[str, dict]:
    try:
        async with span(sess, "coach", model="meta-llama/Llama-3.1-8B-Instruct", sponsor="wandb") as sp:
            text, meta = await _wandb_chat(http, system, user, **kw)
            sp["detail"] = (text or "fallback")[:120]
            return text, meta
    except Exception:  # noqa: BLE001
        return "", {"ms": 0, "model": None, "source": "policy"}


def _msg(sess, text: str, ids: list[str], source: str = "curriculum", **extra) -> dict:
    d = {"type": "guidance", "text": text, "finding_ids": ids, "source": source,
         "coach": public_coach_state(sess)}
    d.update(extra)
    return d


def _touch(sess, step_changed: bool = False) -> None:
    now = time.time()
    c = sess.coach
    c["last_act_ts"] = now
    if step_changed:
        c["awaiting_next"] = False
        c["ready_votes"] = {"ver": None, "n": 0, "idx": c.get("step_index", 0)}
        c["step_ts"] = now
        c["hint_level"] = 0
        c["last_hint_ts"] = 0.0


def _confidence(sess) -> dict:
    twin = sess.twin if isinstance(getattr(sess, "twin", None), dict) else None
    if not twin:
        return {"level": "none", "line": "I can't see your board yet - show it to the camera."}
    comps = twin.get("components") or []
    nets = twin.get("nets") or []
    obs = (twin.get("observation") or "").strip()
    if not comps:
        return {"level": "low", "line": "I see the bench but no parts I can name yet."}
    names = ", ".join(sorted({str(c.get("type")) for c in comps if isinstance(c, dict)})[:5])
    lvl = "high" if nets else "medium"
    line = f"I see {names}" + (f" and {len(nets)} connection(s)." if nets else "; connections still unclear.")
    if obs and lvl == "medium":
        line += f" ({obs[:80]})"
    return {"level": lvl, "line": line}


def ensure_session_coach(sess) -> None:
    if getattr(sess, "coach", None) is None:
        sess.coach = {
            "phase": "ask_project",
            "project_id": None,
            "step_index": 0,
            "last_tip_key": None,
            "intro_sent": False,
            "board": "nano",
            "step_ts": time.time(),
            "last_act_ts": time.time(),
            "hint_level": 0,
            "last_hint_ts": 0.0,
            "pending_check": None,
            "spoken_mistakes": [],
        }
    for k, v in (("board", "nano"), ("hint_level", 0), ("pending_check", None), ("spoken_mistakes", []),
                 ("step_ts", time.time()), ("last_act_ts", time.time()), ("last_hint_ts", 0.0)):
        sess.coach.setdefault(k, v)


def _project(sess):
    c = sess.coach
    if c.get("project"):
        return c["project"]
    return get_project(c.get("project_id") or "blink", board=c.get("board"))


def public_coach_state(sess) -> dict:
    ensure_session_coach(sess)
    c = sess.coach
    project = _project(sess) if c.get("project_id") else None
    step = step_at(project, c["step_index"]) if project else None
    steps_public = None
    if project:
        steps_public = [
            {
                "id": s["id"],
                "title": s["title"],
                "teach": s.get("teach"),
                "action": s.get("action"),
                "pins": s.get("pins"),
                "wires": s.get("wires"),
                "why": s.get("why"),
                "check": s.get("check"),
                "hole_hint": s.get("hole_hint"),
            }
            for s in project["steps"]
        ]
    return {
        "phase": c["phase"],
        "project_id": c.get("project_id"),
        "step_index": c["step_index"],
        "step_total": len(project["steps"]) if project else 0,
        "project": (
            {"id": project["id"], "title": project["title"], "pitch": project["pitch"], "sketch": project.get("sketch"),
             "mcu": project.get("mcu"), "board": project.get("board", c.get("board", "nano")),
             "parts_list": project.get("parts_list") or [], "generated": bool(project.get("generated")),
             "steps": project["steps"]}
            if project else None
        ),
        "step": step,
        "steps": steps_public,
        "projects": list_projects(),
        "board": c.get("board", "nano"),
        "mistakes": public_mistakes(_diag(sess)),
        "awaiting_next": bool(sess.coach.get("awaiting_next")),
        "confidence": _confidence(sess),
    }


_GENERIC_MISTAKES = {"led_reversed", "legs_shorted", "board_straddle", "led_overcurrent", "usb_missing"}


def _diag(sess) -> list[dict]:
    c = sess.coach
    project = _project(sess) if c.get("project_id") else None
    step = step_at(project, c["step_index"]) if project else None
    ms = diagnose(getattr(sess, "twin", None), getattr(sess, "findings", None), step)
    if project and project.get("id") != "blink":  # Blink-specific rules do not apply: generic checks only
        ms = [m for m in ms if m["id"] in _GENERIC_MISTAKES]
    dismissed = set(c.get("dismissed") or [])
    # A fault only counts once its part has been introduced: a missing resistor on step 1 is not a mistake yet,
    # and an earlier step that passed never turns into a failure again.
    first_step = {"led_reversed": 1, "resistor_missing": 2, "resistor_to_5v": 2, "not_same_strip": 2, "gnd_missing": 3}
    idx = c.get("step_index", 0)
    if project and project.get("id") == "blink":
        ms = [m for m in ms if idx >= first_step.get(m["id"], 1)]
    return [m for m in ms if m["id"] not in dismissed]


async def override(sess, http, action: str, index: int | None = None) -> dict | None:
    """Manual override: the user knows better than the vision model. Quiet, undoable by restarting the step."""
    ensure_session_coach(sess)
    c = sess.coach
    idx = c.get("step_index", 0) if index is None else int(index)
    if action in ("complete", "skip"):
        set_step(sess, idx)
        st = advance_step(sess, 1)
        tip = await teach_current_step(sess, http, force=True)
        lead = "Marked as done." if action == "complete" else "Skipped."
        return _msg(sess, f"{lead} {(tip or {}).get('text', '')}".strip(), ["override_" + action], "curriculum")
    if action == "dismiss":
        ids = [m["id"] for m in _diag(sess)]
        c["dismissed"] = sorted(set(c.get("dismissed") or []) | set(ids))
        c["mistake_votes"] = {"ver": None, "seen": {}}
        _touch(sess)
        return _msg(sess, "Understood, I will stop flagging that. Tell me if I get it wrong again.", ["override_dismiss"], "curriculum")
    if action == "recheck":
        sess.force_cosmos = True
        c["mistake_votes"] = {"ver": None, "seen": {}}
        c["ready_votes"] = {"ver": None, "n": 0, "idx": idx}
        return _msg(sess, "Taking another careful look at the board.", ["override_recheck"], "curriculum")
    if action == "restart":
        set_step(sess, idx)
        c["dismissed"] = []
        tip = await teach_current_step(sess, http, force=True)
        return tip
    return None


def start_project(sess, project_id: str = "blink", board: str | None = None, project: dict | None = None) -> dict:
    ensure_session_coach(sess)
    board = normalize_board(board or sess.coach.get("board"))
    if project is None:
        project = get_project(project_id, board=board) or get_project("blink", board=board)
        sess.coach["project"] = None
    else:
        sess.coach["project"] = project
    sess.coach.update({
        "phase": "teaching",
        "project_id": project["id"],
        "step_index": 0,
        "last_tip_key": None,
        "intro_sent": False,
        "board": board,
        "pending_check": None,
        "spoken_mistakes": [],
        "store_key": None,
        "mistakes_log": [],
        "parts_seen": [],
        "prompt": project.get("prompt") or "",
    })
    _touch(sess, True)
    _persist(sess)
    return public_coach_state(sess)


def resume_project(sess, rec: dict) -> dict:
    """Load a stored project record into the session coach."""
    ensure_session_coach(sess)
    project = rec["project"]
    board = normalize_board(rec.get("board") or project.get("board"))
    n = len(project.get("steps") or [])
    sess.coach.update({
        "phase": "teaching", "project": project, "project_id": project["id"], "board": board,
        "step_index": max(0, min(n - 1, int(rec.get("step_index") or 0))), "last_tip_key": None,
        "pending_check": None, "spoken_mistakes": [], "store_key": rec.get("key"),
        "mistakes_log": list(rec.get("mistakes") or []), "parts_seen": list(rec.get("parts_seen") or []),
        "prompt": rec.get("prompt") or "", "intro_sent": True,
    })
    _touch(sess, True)
    return public_coach_state(sess)


def _persist(sess) -> None:
    try:
        import projects_store
        projects_store.schedule_save(sess)
    except Exception:  # noqa: BLE001
        pass


GEN_SYSTEM = (
    "You design beginner breadboard electronics projects. Reply with ONE strict JSON object and nothing else "
    "(double quotes, no comments, no placeholders). Example shape (values are examples):\n"
    '{"id":"button-led","title":"Button controls LED","pitch":"Press a button to light an LED.","mcu":"Arduino Nano",'
    '"sketch":"void setup(){pinMode(5,OUTPUT);}\\nvoid loop(){}",'
    '"parts_list":[{"type":"led","value":"red","qty":1},{"type":"resistor","value":"220","qty":1}],'
    '"steps":[{"id":"led","title":"Add the LED","concept":"LEDs conduct one way.","action":"Place the LED across two rows.",'
    '"teach":"Long leg is the anode.","why":"Reverse polarity blocks current.","check":"Which leg is the anode?",'
    '"hole_hint":"Different rows for each leg.","expect":{"types":["led"]},"pins":["D5","GND"],'
    '"wires":[{"from":"D5","to":"R1.a","color":"#c87941"},{"from":"R1.b","to":"LED1.a","color":"#d6ff4b"}],"parts":["led"]}]}\n'
    "Rules: 4 to 6 steps, last step expect {\"complete\":true} and uploads the sketch. Wires are cumulative (each step lists all wires so far). "
    "Wire endpoints are only board pins or part terminals like R1.a, R1.b, LED1.a (anode), LED1.k (cathode), BTN1.a, BTN1.b. "
    "EVERY LED needs a series 220 ohm resistor between the pin and the LED anode; LED cathode goes to GND. "
    "Never wire a pin directly to GND, 5V or 3V3. Short sentences, one concrete action per step. Sketch max 25 lines."
)


async def generate_project(sess, http, prompt: str, board: str | None) -> tuple[dict | None, str]:
    """LLM -> validated project. Returns (project or None, note)."""
    board = normalize_board(board)
    pins = ("D2..D13, A0..A5, 5V, 3V3, GND" if board == "nano"
            else "GPIO numbers (e.g. GPIO25), 3V3, GND (no 5V, 3.3 V logic)")
    user = f"Project: {prompt}\nBoard: {'Arduino Nano (5 V logic)' if board == 'nano' else 'ESP32 DevKit (3.3 V logic)'}\nValid board pins: {pins}"
    last = "no llm output"
    for attempt in range(2):
        text, _meta = await _llm(sess, http, GEN_SYSTEM, user if attempt == 0 else user + f"\nPrevious attempt invalid: {last}. Fix it.",
                                 max_tokens=2600, timeout=60, temperature=0.2)
        if not text:
            last = "no llm output"
            continue
        try:
            proj = curriculum.parse_project(text, board, prompt)
            return proj, "generated"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"[:160]
            log.warning("raw llm head: %r", text[:160])
            log.warning("project generation invalid: %s", last)
    return None, last


async def start_generated(sess, http, prompt: str, board: str | None) -> tuple[dict, str, bool]:
    """Returns (coach_state, note_for_user, ok). Falls back to Blink on failure."""
    proj, why = await generate_project(sess, http, prompt, board)
    if proj:
        return start_project(sess, proj["id"], board=board, project=proj), f"I designed a custom project: {proj['title']}. {proj['pitch']}", True
    st = start_project(sess, "blink", board=board)
    return st, "I couldn't generate a safe custom circuit for that, so let's start with Blink and build from there.", False


_BUILD_RE = __import__("re").compile(
    r"\b(?:i\s+(?:want|wanna|would like|'d like|need)\s+to\s+(?:build|make|create|wire)|let'?s\s+(?:build|make)|"
    r"(?:build|make|create)\s+(?:me\s+)?(?:a|an|the))\s+(?P<what>.+)", __import__("re").I)


def extract_build_request(text: str) -> str | None:
    m = _BUILD_RE.search(text or "")
    if not m:
        return None
    what = m.group("what").strip(" .!?")
    if not what or what.lower().startswith("blink"):
        return None
    return what


def advance_step(sess, delta: int = 1) -> dict:
    ensure_session_coach(sess)
    project = _project(sess)
    if not project:
        return public_coach_state(sess)
    n = len(project["steps"])
    sess.coach["step_index"] = max(0, min(n - 1, sess.coach["step_index"] + delta))
    sess.coach["last_tip_key"] = None
    _touch(sess, True)
    _persist(sess)
    return public_coach_state(sess)


def set_step(sess, index: int) -> dict:
    ensure_session_coach(sess)
    project = _project(sess)
    if project:
        sess.coach["step_index"] = max(0, min(len(project["steps"]) - 1, index))
        sess.coach["last_tip_key"] = None
        _touch(sess, True)
        _persist(sess)
    return public_coach_state(sess)


def _fallback_tip(step: dict) -> str:
    return f"{step['concept']} {step['action']} {step['teach']}"


def ask_project_opener() -> str:
    return (
        "What would you like to build on the breadboard? "
        "Say “Blink” and we’ll wire an external LED on Arduino Nano (D13 → 220Ω → LED anode, cathode → GND), "
        "or say “Blink on ESP32” if that’s your board."
    )


async def teach_current_step(sess, http: aiohttp.ClientSession, *, force: bool = False) -> dict | None:
    """Proactive tip for the active curriculum step (not a plan readout)."""
    ensure_session_coach(sess)
    if sess.coach["phase"] != "teaching":
        return None
    project = _project(sess)
    step = step_at(project, sess.coach["step_index"])
    if not step:
        return None
    key = f"step:{step['id']}:{sess.coach['step_index']}"
    if not force and sess.coach.get("last_tip_key") == key:
        return None
    twin = sess.twin or {}
    system = (
        "You are CURRENT, a calm electronics teacher at a breadboard. "
        "Start by saying what you SEE (observation / placements / hole letters) using ONLY the twin below. "
        "If twin.scene is 'other' or there are no components, say plainly that you cannot see the board yet "
        "and ask them to point the camera at the Nano/ESP32 and breadboard; NEVER invent parts or wiring. Then "
        f"give ONE concrete next wire action for the {project['title']} project on {project['mcu']}. "
        "Do NOT recite the whole plan. Max 4 short sentences. Name the signal pin and GND correctly. Then one short sentence on WHY. "
        "If placements list breadboard holes (e.g. E12), mention whether they look right for this step."
    )
    user = json.dumps({
        "project": project["title"],
        "step": {
            "id": step["id"],
            "title": step["title"],
            "concept": step["concept"],
            "action": step["action"],
            "teach": step["teach"],
            "why": step.get("why"),
            "hole_hint": step.get("hole_hint"),
        },
        "twin": {
            "scene": twin.get("scene"),
            "observation": twin.get("observation"),
            "components": twin.get("components"),
            "nets": twin.get("nets"),
            "placements": twin.get("placements"),
            "wiring_check": twin.get("wiring_check"),
        },
        "step_index": sess.coach["step_index"] + 1,
        "step_total": len(project["steps"]),
    })
    text, meta = await _llm(sess, http, system, user)
    if not text:
        text = _fallback_tip(step)
        meta = {"ms": 0, "source": "curriculum", "model": None}
    sess.coach["last_tip_key"] = key
    return {
        "type": "guidance",
        "text": text,
        "finding_ids": [f"step_{step['id']}"],
        "source": meta.get("source"),
        "model": meta.get("model"),
        "ms": meta.get("ms"),
        "coach": public_coach_state(sess),
    }


async def converse(sess, http: aiohttp.ClientSession, question: str) -> dict:
    ensure_session_coach(sess)
    q = (question or "").strip()
    low = q.lower()
    _touch(sess)

    board_word = "esp32" if ("esp" in low) else ("nano" if ("nano" in low or "arduino" in low) else None)
    if board_word and sess.coach["phase"] == "teaching" and sess.coach.get("board") != board_word and any(
            w in low for w in ("use", "switch", "i have", "i'm using", "im using", "esp32", "esp 32")):
        cur_p = sess.coach.get("project")
        if cur_p and cur_p.get("generated"):
            st, _n, _ok = await start_generated(sess, http, cur_p.get("prompt") or cur_p["title"], board_word)
        else:
            st = start_project(sess, sess.coach.get("project_id") or "blink", board=board_word)
        tip = await teach_current_step(sess, http, force=True)
        return _msg(sess, f"Switched to {board_word.upper()}. " + ((tip or {}).get("text") or ""), ["step_orient"])

    pc = sess.coach.get("pending_check")
    if pc and sess.coach["phase"] == "teaching" and q and not any(w in low for w in ("next", "back", "previous")):
        sess.coach["pending_check"] = None
        return _msg(sess, _grade_check(pc, q), ["chat"], "curriculum")

    # Free-text "I want to build a ..." -> generate any project
    what = extract_build_request(q)
    if what and (sess.coach["phase"] == "ask_project" or not any(w in low for w in ("next", "back"))):
        st, note, _ok = await start_generated(sess, http, what, board_word or sess.coach.get("board"))
        tip = await teach_current_step(sess, http, force=True)
        return {"type": "guidance", "text": (note + " " + ((tip or {}).get("text") or "")).strip(),
                "finding_ids": (tip or {}).get("finding_ids") or [], "source": (tip or {}).get("source") or "curriculum",
                "ms": (tip or {}).get("ms"), "coach": public_coach_state(sess)}

    # Project selection / demo path
    if sess.coach["phase"] == "ask_project":
        wants_blink = any(
            w in low
            for w in ("blink", "led", "arduino", "nano", "demo", "yes", "start", "build", "ok")
        )
        if wants_blink or not q:
            start_project(sess, "blink", board=board_word)
            tip = await teach_current_step(sess, http, force=True)
            opener = (
                f"Great, Blink it is on {'ESP32' if sess.coach.get('board') == 'esp32' else 'Arduino Nano'}. Circuit: {'GPIO2' if sess.coach.get('board') == 'esp32' else 'D13'} → 220Ω → LED anode; cathode → GND. "
                "Arm the camera when the board is in frame."
            )
            text = opener + (" " + tip["text"] if tip else "")
            return {
                "type": "guidance",
                "text": text,
                "finding_ids": (tip or {}).get("finding_ids") or [],
                "source": (tip or {}).get("source") or "curriculum",
                "ms": (tip or {}).get("ms"),
                "coach": public_coach_state(sess),
            }
        return {
            "type": "guidance",
            "text": ask_project_opener(),
            "finding_ids": [],
            "source": "curriculum",
            "coach": public_coach_state(sess),
        }

    yes = sess.coach.get("awaiting_next") and low.strip(" .!") in ("yes", "yeah", "yep", "sure", "ok", "okay", "go", "go on", "yes please")
    if yes or any(w in low for w in ("next", "done", "finished", "continue", "got it", "ready")):
        st = advance_step(sess, 1)
        tip = await teach_current_step(sess, http, force=True)
        text = tip["text"] if tip else f"On to step {st['step_index'] + 1}."
        return {
            "type": "guidance",
            "text": text,
            "finding_ids": (tip or {}).get("finding_ids") or [],
            "source": (tip or {}).get("source") or "curriculum",
            "coach": st,
            "ms": (tip or {}).get("ms"),
        }

    if "back" in low or "previous" in low:
        st = advance_step(sess, -1)
        tip = await teach_current_step(sess, http, force=True)
        return {
            "type": "guidance",
            "text": tip["text"] if tip else "Stepped back.",
            "finding_ids": [],
            "source": "curriculum",
            "coach": st,
        }

    if any(w in low for w in ("before", "last time", "mistake", "history")):
        from history import search_my_mistakes
        ans = await search_my_mistakes(http, q)
        return {
            "type": "guidance",
            "text": ans.get("text") or "No prior session match in your VAST index yet.",
            "finding_ids": ["history"],
            "source": "vast",
            "evidence": ans.get("evidence"),
            "coach": public_coach_state(sess),
        }

    project = _project(sess) if sess.coach.get("project_id") else None
    step = step_at(project, sess.coach["step_index"]) if project else None
    system = (
        "You are CURRENT, a proactive electronics teacher. "
        "Answer the student's spoken question using the active project step and vision twin. "
        "Be concrete about pins and polarity. 2-4 short sentences. No full plan dump."
    )
    user = json.dumps({
        "question": q,
        "coach": public_coach_state(sess),
        "step": step,
        "twin": sess.twin,
    })
    text, meta = await _llm(sess, http, system, user)
    if not text:
        if step:
            text = f"For {step['title']}: {step['action']}"
        else:
            text = "Ask a wiring question, or say “next” when that step is done."
        meta = {"source": "curriculum", "ms": 0}
    return {
        "type": "guidance",
        "text": text,
        "finding_ids": ["chat"],
        "source": meta.get("source"),
        "model": meta.get("model"),
        "ms": meta.get("ms"),
        "coach": public_coach_state(sess),
    }


def _grade_check(pc: dict, answer: str) -> str:
    low = answer.lower()
    keys = pc.get("keys") or []
    ok = any(k in low for k in keys) if keys else True
    why = pc.get("why") or ""
    if ok:
        return "Exactly right. Let's keep going: say next when you're ready."
    return f"Not quite. {why} Say next when you're ready."


_CHECK_KEYS = {
    "orient": ["d13", "gpio2", "5", "3.3", "high"],
    "led": ["long", "anode"],
    "resistor": ["14", "15", "6.8", "7", "ma"],
    "gnd": ["gnd", "ground", "0"],
    "flash": ["0", "zero", "low", "ground"],
}


def _celebrate(sess, done_step: dict) -> dict:
    """<=1 sentence celebration + why + optional quiz question."""
    chk = done_step.get("check")
    sess.coach["pending_check"] = (
        {"step": done_step["id"], "keys": _CHECK_KEYS.get(done_step["id"], []), "why": done_step.get("why", "")}
        if chk else None)
    text = f"Nice, {done_step['title'].lower()} looks done. {done_step.get('why', '')}".strip()
    if chk:
        text += " " + chk
    return _msg(sess, text, ["step_complete"])


def _mistake_msg(sess, m: dict) -> dict:
    seen = sess.twin.get("observation") if isinstance(sess.twin, dict) else None
    text = f"It looks like {m['title'].lower()}, though I could be wrong. If it is: {m['fix']}"
    ids = [m["id"]]
    return _msg(sess, text, ids, "verifier", mistakes=public_mistakes([m]), what_i_see=seen)


async def mistake_alert(sess, http) -> dict | None:
    ensure_session_coach(sess)
    if sess.coach["phase"] != "teaching":
        return None
    spoken = sess.coach["spoken_mistakes"]
    # The VLM's traced nets wobble between frames. Only speak a mistake once two consecutive
    # Cosmos analyses agree on it (votes advance once per new twin, not per tick).
    ver = getattr(sess, "last_cosmos_ts", 0)
    votes = sess.coach.setdefault("mistake_votes", {"ver": None, "seen": {}})
    diag = _diag(sess)
    if votes["ver"] != ver:
        votes["ver"] = ver
        ids = {m["id"] for m in diag}
        votes["seen"] = {i: votes["seen"].get(i, 0) + 1 for i in ids}
    for m in diag:
        if votes["seen"].get(m["id"], 0) < 2:
            continue
        if m["severity"] == "critical" or m["severity"] == "warning":
            key = f"{m['id']}@{sess.coach['step_index']}"
            if key not in spoken:
                spoken.append(key)
                _touch(sess)
                sess.coach.setdefault("mistakes_log", []).append(
                    {"id": m["id"], "title": m["title"], "step": sess.coach["step_index"], "ts": time.time()})
                _persist(sess)
                msg = _mistake_msg(sess, m)
                try:  # Cosmos-Embed1 memory: have we seen this mistake before?
                    from sponsors import embed_memory
                    desc = f"{m['title']}. {m['explain']}"
                    prior = await embed_memory.recall(sess, desc, http=http)
                    if prior:
                        msg["text"] += " That is the same slip as earlier, so let's lock it in this time."
                    await embed_memory.remember(sess, desc, http=http)
                except Exception:  # noqa: BLE001
                    pass
                return msg
    return None


async def tick(sess, http) -> dict | None:
    """Call every few seconds. Returns a guidance dict to broadcast, or None.

    Order: new mistake -> idle hint ladder (nudge, hint, exact hole) after ~20 s of silence.
    """
    ensure_session_coach(sess)
    c = sess.coach
    if c["phase"] != "teaching":
        return None
    al = await mistake_alert(sess, http)
    if al:
        return al
    now = time.time()
    if now - c["last_act_ts"] < IDLE_SECS or now - c["last_hint_ts"] < HINT_GAP_SECS:
        return None
    step = step_at(_project(sess), c["step_index"])
    if not step:
        return None
    lvl = c["hint_level"]
    if lvl == 0:
        text = f"Still on {step['title'].lower()}? {step['action']}"
    elif lvl == 1:
        text = f"Hint: {step['teach']} {step['why']}" if step.get("why") else f"Hint: {step['teach']}"
    else:
        text = f"Exactly where: {step.get('hole_hint') or step['action']}"
    c["hint_level"] = min(lvl + 1, 2)
    c["last_hint_ts"] = now
    return _msg(sess, text, [f"step_{step['id']}"], hint_level=lvl + 1)


async def on_twin_update(sess, http: aiohttp.ClientSession) -> dict | None:
    """After Cosmos twin: mistakes first, then step progress (celebrate) + teach."""
    ensure_session_coach(sess)
    if sess.coach["phase"] != "teaching":
        return None
    project = _project(sess)
    if not project:
        return None
    al = await mistake_alert(sess, http)
    if al:
        return al
    try:
        import projects_store
        before = list(sess.coach.get("parts_seen") or [])
        if projects_store.parts_seen(sess) != before:
            sess.coach["parts_seen"] = projects_store.parts_seen(sess)
            _persist(sess)
    except Exception:  # noqa: BLE001
        pass
    if project.get("id") != "blink":  # no blink heuristics for custom projects; user says "next"
        return await teach_current_step(sess, http, force=False)
    suggested = infer_step_from_twin(project, sess.twin)
    idx = sess.coach["step_index"]
    if suggested > idx and not sess.coach.get("awaiting_next"):
        # Looks done. Two consecutive twins must agree, then ASK before moving on (never auto-advance on one noisy frame).
        ver = getattr(sess, "last_cosmos_ts", 0)
        rv = sess.coach.setdefault("ready_votes", {"ver": None, "n": 0, "idx": idx})
        if rv["idx"] != idx:
            rv.update(ver=None, n=0, idx=idx)
        if rv["ver"] != ver:
            rv["ver"] = ver
            rv["n"] += 1
        if rv["n"] >= 2:
            done = step_at(project, idx)
            sess.coach["awaiting_next"] = True
            _touch(sess)
            cel = _celebrate(sess, done)
            cel["text"] = (cel["text"].split(" " + (done.get("check") or "\0"))[0]
                           + ' Ready for the next step? Say "next" or tap Continue.')
            sess.coach["pending_check"] = None  # confirmation, not a quiz, is what we wait for
            cel["step_ready"] = True
            cel["coach"] = public_coach_state(sess)
            return cel
        return None
    if sess.coach.get("awaiting_next"):
        return None  # waiting for the user to confirm; don't talk over them
    return await teach_current_step(sess, http, force=False)
