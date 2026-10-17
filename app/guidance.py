"""Verified-guidance gate. LLM may only phrase verifier findings."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from config import settings

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore

log = logging.getLogger("guidance")

_MODEL_CACHE: str | None = None


async def list_and_pick_model(http: aiohttp.ClientSession) -> str | None:
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE
    if not settings.wandb_ready:
        return None
    headers = {
        "Authorization": f"Bearer {settings.wandb_key}",
        "OpenAI-Project": f"{settings.wandb_team}/{settings.wandb_project}",
    }
    try:
        async with http.get(settings.wandb_base + "/models", headers=headers, timeout=20) as resp:
            if resp.status >= 400:
                log.warning("wandb_models_http=%s", resp.status)
                return None
            data = await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("wandb_models_error=%s", type(e).__name__)
        return None
    models = data.get("data") or data.get("models") or []
    ids = []
    for m in models:
        if isinstance(m, dict):
            ids.append(m.get("id") or m.get("name"))
        elif isinstance(m, str):
            ids.append(m)
    ids = [i for i in ids if i]
    # Prefer models that typically support streaming + JSON
    preferred = [
        "meta-llama/Llama-3.1-8B-Instruct",
        "gpt-4o-mini",
        "openai/gpt-4o-mini",
        "meta-llama/Meta-Llama-3.1-8B-Instruct",
    ]
    for p in preferred:
        if p in ids:
            _MODEL_CACHE = p
            return p
    # any instruct / mini
    for i in ids:
        low = i.lower()
        if "instruct" in low or "mini" in low or "gpt" in low:
            _MODEL_CACHE = i
            return i
    _MODEL_CACHE = ids[0] if ids else None
    return _MODEL_CACHE


def gate_message(text: str, allowed_finding_ids: set[str], findings: list[dict]) -> tuple[bool, str]:
    """Reject guidance that invents facts not in findings."""
    if not text or not text.strip():
        return False, "empty"
    words = text.strip().split()
    if len(words) > 20:
        text = " ".join(words[:20])
    # twin_obs / step_complete are explicit non-finding channels
    if allowed_finding_ids & {"twin_obs", "step_complete", "perception_error"}:
        return True, text
    if not allowed_finding_ids and "step" not in text.lower():
        return False, "no_finding_ids"
    # UnGrounded claim heuristics: numbers/parts not present in findings text
    blob = " ".join(f["message"] for f in findings).lower()
    blob += " " + " ".join(allowed_finding_ids).lower()
    # reject if mentions a finding id pattern that isn't allowed
    claimed_ids = set(re.findall(r"\b([a-z]+_(?:[a-z0-9_]+))\b", text.lower()))
    # also reject absolute claims about components never mentioned
    forbidden_tokens = []
    for tok in re.findall(r"\b([a-z]{2,}\d+)\b", text.lower()):
        if tok not in blob and tok not in {"led", "resistor"}:
            # component-like ids
            if any(ch.isdigit() for ch in tok):
                forbidden_tokens.append(tok)
    # Hard reject: sentences asserting facts with no overlap to finding messages
    finding_words = set(re.findall(r"[a-z0-9]+", blob))
    text_words = set(re.findall(r"[a-z0-9]+", text.lower()))
    stop = {"the", "a", "an", "to", "and", "or", "of", "in", "on", "is", "it", "you", "your", "add", "next", "please", "now", "with"}
    overlap = (text_words - stop) & (finding_words - stop)
    if findings and len(overlap) < 1:
        return False, "ungrounded"
    if forbidden_tokens:
        return False, "ungrounded_component"
    return True, text


async def coach_from_twin(
    http: "aiohttp.ClientSession",
    twin: dict,
    findings: list[dict] | None = None,
) -> tuple[str | None, dict]:
    """Pipe Cosmos twin (and optional findings) to W&B LLM for a short tip."""
    meta: dict[str, Any] = {"ms": 0, "model": None, "source": "twin", "finding_ids": ["cosmos_twin"]}
    comps = twin.get("components") or []
    if not comps:
        return None, meta
    # Local fallback from twin itself (always visible even if W&B is down)
    kinds = ", ".join(f"{c.get('id')}={c.get('type')}" for c in comps[:6])
    fallback = f"I see {kinds}. Next: check polarity and series resistance."
    fallback = " ".join(fallback.split()[:20])

    model = await list_and_pick_model(http)
    if not model or not settings.wandb_ready:
        return fallback, meta

    meta["model"] = model
    headers = {
        "Authorization": f"Bearer {settings.wandb_key}",
        "Content-Type": "application/json",
        "OpenAI-Project": f"{settings.wandb_team}/{settings.wandb_project}",
    }
    payload = {
        "model": model,
        "temperature": 0.2,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an electronics bench coach. "
                    "Given a circuit twin JSON from a vision model, give ONE next-step tip. "
                    "At most 20 words. Output JSON {\"tip\":\"...\"}. "
                    "Stay faithful to the twin components/nets; do not invent parts."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"twin": twin, "findings": findings or []}),
            },
        ],
    }
    t0 = time.perf_counter()
    try:
        async with http.post(
            settings.wandb_base + "/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            raw = await resp.json()
            meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status >= 400:
                return fallback, meta
            content = raw["choices"][0]["message"]["content"]
            try:
                tip = str(json.loads(content).get("tip") or fallback)
            except Exception:  # noqa: BLE001
                tip = fallback
            tip = " ".join(tip.split()[:20])
            meta["source"] = "wandb"
            return tip, meta
    except Exception:  # noqa: BLE001
        meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return fallback, meta


async def phrase_tip(http: aiohttp.ClientSession, findings: list[dict], finding_ids: list[str]) -> tuple[str | None, dict]:
    meta: dict[str, Any] = {"ms": 0, "model": None, "source": "template"}
    msgs = [f for f in findings if f["id"] in finding_ids]
    if not msgs:
        return None, meta
    # Template fallback (always grounded)
    f0 = msgs[0]
    template = {
        "LED_NO_SERIES_R": "Add a series resistor before powering the LED.",
        "LED_REVERSED": "Flip the LED; long leg is the anode.",
        "SUPPLY_SHORT": "Disconnect the short across the supply now.",
        "LED_CURRENT_GT_20MA": "Raise the series resistance; LED current is too high.",
        "FLOATING_NET": "Finish wiring the floating component.",
        "RESISTOR_OVERPOWER": "Use a higher wattage resistor.",
    }.get(f0["rule"], f0["message"][:80])
    words = template.split()
    tip = " ".join(words[:20])

    model = await list_and_pick_model(http)
    if not model or not settings.wandb_ready:
        meta["model"] = None
        return tip, meta
    meta["model"] = model
    headers = {
        "Authorization": f"Bearer {settings.wandb_key}",
        "Content-Type": "application/json",
        "OpenAI-Project": f"{settings.wandb_team}/{settings.wandb_project}",
    }
    payload = {
        "model": model,
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You phrase electronics coaching tips. "
                    "You may ONLY restate the provided verifier findings. "
                    "Do not add facts. Output JSON {\"tip\":\"...\"} max 20 words."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"findings": msgs, "finding_ids": finding_ids}),
            },
        ],
    }
    t0 = time.perf_counter()
    try:
        async with http.post(
            settings.wandb_base + "/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            raw = await resp.json()
            meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status >= 400:
                return tip, meta
            content = raw["choices"][0]["message"]["content"]
            try:
                obj = json.loads(content)
                candidate = str(obj.get("tip") or tip)
            except Exception:  # noqa: BLE001
                candidate = tip
            ok, gated = gate_message(candidate, set(finding_ids), msgs)
            if ok:
                meta["source"] = "wandb"
                return gated, meta
            return tip, meta
    except Exception:  # noqa: BLE001
        meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return tip, meta


async def maybe_speak(sess, http: aiohttp.ClientSession, trigger: str, question: str | None = None) -> dict | None:
    """Proactive policy: hazard / step-complete / voice ask. Cooldown 8s. No repeats."""
    now = time.time()
    findings = sess.findings or []
    if trigger == "voice" and question:
        return await answer_question(sess, http, question)

    critical = [f for f in findings if f.get("severity") == "critical"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    actionable = critical or warnings
    new_ids = [f["id"] for f in actionable if f["id"] not in sess.spoken_finding_ids]
    if not new_ids:
        # step-complete: previously had hazard, now clean
        if trigger == "hazard_or_step" and not actionable and sess.spoken_finding_ids:
            if "step_complete" in sess.spoken_finding_ids:
                return None
            if now - sess.last_guidance_ts < settings.guidance_cooldown_s:
                return None
            tip = "Nice — that hazard looks fixed. Continue the next connection."
            sess.spoken_finding_ids.add("step_complete")
            sess.last_guidance_ts = now
            msg = {
                "text": tip,
                "finding_ids": ["step_complete"],
                "ms": 0,
                "source": "policy",
            }
            sess.guidance_log.append(msg)
            return msg
        # No hazards: one twin-grounded observation (components actually seen)
        if trigger == "hazard_or_step" and sess.twin and "twin_obs" not in sess.spoken_finding_ids:
            comps = sess.twin.get("components") or []
            if comps and now - sess.last_guidance_ts >= 2:
                kinds = ", ".join(f"{c.get('id')}={c.get('type')}" for c in comps[:6])
                tip = f"Twin sees {kinds}. No verifier hazards."
                words = tip.split()
                tip = " ".join(words[:20])
                sess.spoken_finding_ids.add("twin_obs")
                sess.last_guidance_ts = now
                msg = {
                    "text": tip,
                    "finding_ids": ["twin_obs"],
                    "ms": 0,
                    "source": "twin",
                }
                sess.guidance_log.append(msg)
                return msg
        return None
    if now - sess.last_guidance_ts < min(settings.guidance_cooldown_s, 3.0):
        return None
    tip, meta = await phrase_tip(http, findings, new_ids[:3])
    if not tip:
        return None
    ok, gated = gate_message(tip, set(new_ids), findings)
    if not ok:
        # Verifier message itself is the ground truth
        f0 = next(f for f in actionable if f["id"] in new_ids)
        gated = " ".join(str(f0["message"]).split()[:20])
        meta = {"ms": 0, "source": "verifier"}
    for fid in new_ids[:3]:
        sess.spoken_finding_ids.add(fid)
    # Allow a later twin_obs after hazards clear
    sess.spoken_finding_ids.discard("twin_obs")
    sess.last_guidance_ts = now
    msg = {
        "text": gated,
        "finding_ids": new_ids[:3],
        "ms": meta.get("ms"),
        "model": meta.get("model"),
        "source": meta.get("source"),
    }
    log.info("guidance finding_ids=%s", ",".join(msg["finding_ids"]))
    sess.guidance_log.append(msg)
    return msg


async def answer_question(sess, http: aiohttp.ClientSession, question: str) -> dict:
    findings = sess.findings or []
    twin = sess.twin or {}
    q = question.lower()
    # history intent
    if "mistake before" in q or "have i made" in q or "last session" in q:
        from history import search_my_mistakes
        ans = await search_my_mistakes(http, question)
        return {"text": ans.get("text", "Unknown."), "finding_ids": [], "source": "history", "evidence": ans.get("evidence")}

    if not twin and not findings:
        return {"text": "I do not know yet; no twin is available.", "finding_ids": [], "source": "policy"}
    tip, meta = await coach_from_twin(http, twin or {}, findings=findings)
    return {
        "text": tip or "I do not know from the current twin.",
        "finding_ids": meta.get("finding_ids") or [],
        "source": meta.get("source") or "llm",
        "ms": meta.get("ms"),
        "model": meta.get("model"),
    }
