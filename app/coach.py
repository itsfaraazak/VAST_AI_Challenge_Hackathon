"""Proactive teacher: curriculum + twin + W&B conversation."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from config import settings
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


async def _wandb_chat(http: aiohttp.ClientSession, system: str, user: str) -> tuple[str, dict]:
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
        "temperature": 0.3,
        "max_tokens": 220,
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
            timeout=aiohttp.ClientTimeout(total=45),
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


async def _llm(sess, http, system: str, user: str) -> tuple[str, dict]:
    try:
        async with span(sess, "coach", model="meta-llama/Llama-3.1-8B-Instruct", sponsor="wandb") as sp:
            text, meta = await _wandb_chat(http, system, user)
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
            {"id": project["id"], "title": project["title"], "pitch": project["pitch"], "sketch": project.get("sketch")}
            if project else None
        ),
        "step": step,
        "steps": steps_public,
        "projects": list_projects(),
        "board": c.get("board", "nano"),
        "mistakes": public_mistakes(_diag(sess)),
        "confidence": _confidence(sess),
    }


def _diag(sess) -> list[dict]:
    c = sess.coach
    project = get_project(c.get("project_id") or "blink") if c.get("project_id") else None
    step = step_at(project, c["step_index"]) if project else None
    return diagnose(getattr(sess, "twin", None), getattr(sess, "findings", None), step)


def start_project(sess, project_id: str = "blink", board: str | None = None) -> dict:
    ensure_session_coach(sess)
    board = normalize_board(board or sess.coach.get("board"))
    project = get_project(project_id, board=board) or get_project("blink", board=board)
    sess.coach.update({
        "phase": "teaching",
        "project_id": project["id"],
        "step_index": 0,
        "last_tip_key": None,
        "intro_sent": False,
        "board": board,
        "pending_check": None,
        "spoken_mistakes": [],
    })
    _touch(sess, True)
    return public_coach_state(sess)


def advance_step(sess, delta: int = 1) -> dict:
    ensure_session_coach(sess)
    project = _project(sess)
    if not project:
        return public_coach_state(sess)
    n = len(project["steps"])
    sess.coach["step_index"] = max(0, min(n - 1, sess.coach["step_index"] + delta))
    sess.coach["last_tip_key"] = None
    _touch(sess, True)
    return public_coach_state(sess)


def set_step(sess, index: int) -> dict:
    ensure_session_coach(sess)
    project = _project(sess)
    if project:
        sess.coach["step_index"] = max(0, min(len(project["steps"]) - 1, index))
        sess.coach["last_tip_key"] = None
        _touch(sess, True)
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
        f"give ONE concrete next wire action for {project['mcu']} Blink. "
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
        st = start_project(sess, sess.coach.get("project_id") or "blink", board=board_word)
        tip = await teach_current_step(sess, http, force=True)
        return _msg(sess, f"Switched to {board_word.upper()}. " + ((tip or {}).get("text") or ""), ["step_orient"])

    pc = sess.coach.get("pending_check")
    if pc and sess.coach["phase"] == "teaching" and q and not any(w in low for w in ("next", "back", "previous")):
        sess.coach["pending_check"] = None
        return _msg(sess, _grade_check(pc, q), ["chat"], "curriculum")

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

    if any(w in low for w in ("next", "done", "finished", "continue", "got it", "ready")):
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
        "Answer the student's spoken question using the active Blink step and vision twin. "
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
    text = f"I see {m['title'].lower()}. That matters because {m['explain']} {m['fix']}"
    ids = [m["id"]]
    return _msg(sess, text, ids, "verifier", mistakes=public_mistakes([m]), what_i_see=seen)


async def mistake_alert(sess, http) -> dict | None:
    ensure_session_coach(sess)
    if sess.coach["phase"] != "teaching":
        return None
    spoken = sess.coach["spoken_mistakes"]
    for m in _diag(sess):
        if m["severity"] == "critical" or m["severity"] == "warning":
            key = f"{m['id']}@{sess.coach['step_index']}"
            if key not in spoken:
                spoken.append(key)
                _touch(sess)
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
    suggested = infer_step_from_twin(project, sess.twin)
    idx = sess.coach["step_index"]
    if suggested > idx and suggested <= idx + 1:
        done = step_at(project, idx)
        sess.coach["step_index"] = suggested
        sess.coach["last_tip_key"] = None
        _touch(sess, True)
        cel = _celebrate(sess, done)
        tip = await teach_current_step(sess, http, force=False)
        if tip:
            cel["text"] = cel["text"] + " Next: " + tip["text"]
        return cel
    return await teach_current_step(sess, http, force=False)
