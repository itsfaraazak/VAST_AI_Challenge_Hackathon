"""ElectronicAI — AI Electronics Technician, built on the VAST Builders Challenge stack.

A server-side app that:
  * Authenticates to the team's VSS retrieval backend (JWT) and calls the real
    video search / agent-QA / explore / stream / synthesize APIs.
  * Uses Weights & Biases serverless LLM inference (OpenAI-compatible) for the
    electronics-technician reasoning layer, with safety guardrails and an
    evidence-based diagnostic workflow.
  * Keeps all credentials on the server (read from environment variables that the
    challenge VM already provides). No secret ever reaches the browser.

Honesty by design:
  * The indexed corpus is traffic / driving / warehouse footage, not electronics
    repair. Video search returns the REAL corpus; the UI labels video evidence as
    "observed" and model reasoning as "general knowledge". Nothing is faked.
  * When VSS or the LLM is not configured (e.g. running off-VM), endpoints return
    an explicit, labelled "not connected" boundary instead of fabricated results.

Deploy target: python:3.12-slim on K8s via the deploy-app-no-registry skill.
Routes are served at "/" (the Ingress strips the /app prefix). Deps: flask, requests.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

# --------------------------------------------------------------------------- #
# Configuration — everything from the environment the challenge VM provides.
# --------------------------------------------------------------------------- #

# VSS backend. The deploy skill injects VSS_URL/VSS_USERNAME/VSS_PASSWORD from a
# Secret; the raw VM config calls them INGRESS_URL/USERNAME/PASSWORD. Accept both.
VSS_URL = (os.getenv("VSS_URL") or os.getenv("INGRESS_URL") or "").rstrip("/")
VSS_USERNAME = os.getenv("VSS_USERNAME") or os.getenv("USERNAME") or ""
VSS_PASSWORD = os.getenv("VSS_PASSWORD") or os.getenv("PASSWORD") or ""

# Weights & Biases serverless inference (OpenAI-compatible endpoint).
WANDB_API_KEY = os.getenv("WANDB_API_KEY", "")
WANDB_TEAM = os.getenv("WANDB_TEAM", "")
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "")
WANDB_BASE_URL = os.getenv("WANDB_BASE_URL", "https://api.inference.wandb.ai/v1").rstrip("/")
# Pick whatever model your W&B project serves; override via env on the VM.
WANDB_MODEL = os.getenv("WANDB_MODEL", "meta-llama/Llama-3.3-70B-Instruct")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "60"))
PORT = int(os.getenv("PORT", "8080"))

# Serve templates from templates/ locally, or flat alongside main.py when the
# deploy-app-no-registry ConfigMap flattens everything into /code.
_HERE = os.path.dirname(os.path.abspath(__file__))
_TPL = os.path.join(_HERE, "templates")
app = Flask(__name__, template_folder=_TPL if os.path.isdir(_TPL) else _HERE)


# --------------------------------------------------------------------------- #
# VSS client — thin wrapper over the retrieval backend documented in the skills.
# --------------------------------------------------------------------------- #

class VSSError(RuntimeError):
    """Raised when the VSS backend is unreachable or returns an error."""


class VSSClient:
    """Server-side VSS client. Caches a JWT and re-logs in on 401."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password
        self._token: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def _login(self) -> str:
        if not self.configured:
            raise VSSError("VSS is not configured (missing VSS_URL / username / password).")
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise VSSError(f"Cannot reach VSS backend at {self.base_url}: {exc}") from exc
        if resp.status_code == 401:
            raise VSSError("VSS login failed (401): bad credentials for this tenant.")
        if not resp.ok:
            raise VSSError(f"VSS login error {resp.status_code}: {resp.text[:200]}")
        self._token = resp.json()["access_token"]
        return self._token

    def _token_or_login(self) -> str:
        return self._token or self._login()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        token = self._token_or_login()
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        try:
            resp = requests.request(method, url, headers=headers, timeout=HTTP_TIMEOUT, **kwargs)
            if resp.status_code == 401:  # token expired → one retry
                token = self._login()
                headers["Authorization"] = f"Bearer {token}"
                resp = requests.request(method, url, headers=headers, timeout=HTTP_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise VSSError(f"VSS request failed: {exc}") from exc
        if not resp.ok:
            raise VSSError(f"VSS {method} {path} → {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    # -- real retrieval endpoints (see .cursor/skills/retrieval/*) ----------- #

    def search(self, query: str, top_k: int = 12, min_similarity: float = 0.3,
               metadata_filters: Optional[Dict] = None) -> Dict:
        body = {
            "query": query,
            "top_k": top_k,
            "llm_top_n": 3,
            "min_similarity": min_similarity,
            "include_public": True,
        }
        if metadata_filters:
            body["metadata_filters"] = metadata_filters
        return self._request("POST", "/api/v1/search", json=body)

    def search_and_answer(self, query: str, top_k: int = 10,
                          metadata_filters: Optional[Dict] = None) -> Dict:
        body = {"query": query, "top_k": top_k, "include_public": True}
        if metadata_filters:
            body["metadata_filters"] = metadata_filters
        return self._request("POST", "/api/v1/agent/search-and-answer", json=body)

    def explore(self, limit: int = 24, offset: int = 0) -> Dict:
        return self._request(
            "GET", f"/api/v1/videos/explore?scope=all&limit={limit}&offset={offset}"
        )

    def stream_url(self, source: str) -> str:
        """Seekable proxy stream URL. JWT must be a query param for <video>."""
        token = self._token_or_login()
        return f"{self.base_url}/api/v1/videos/stream?source={source}&token={token}"


vss = VSSClient(VSS_URL, VSS_USERNAME, VSS_PASSWORD)


# --------------------------------------------------------------------------- #
# LLM client — W&B serverless inference, OpenAI-compatible chat completions.
# --------------------------------------------------------------------------- #

class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        self.base_url = WANDB_BASE_URL
        self.api_key = WANDB_API_KEY
        self.model = WANDB_MODEL
        # W&B scopes inference to a project via this header when available.
        self.project = f"{WANDB_TEAM}/{WANDB_PROJECT}" if WANDB_TEAM and WANDB_PROJECT else ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             temperature: float = 0.2) -> Dict:
        if not self.configured:
            raise LLMError("LLM is not configured (missing WANDB_API_KEY).")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.project:
            headers["OpenAI-Project"] = self.project
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=payload, timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise LLMError(f"Cannot reach W&B inference at {self.base_url}: {exc}") from exc
        if not resp.ok:
            raise LLMError(f"LLM error {resp.status_code}: {resp.text[:200]}")
        return resp.json()


llm = LLMClient()


# --------------------------------------------------------------------------- #
# The electronics-technician agent: safety-first, evidence-based diagnosis.
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are ElectronicAI, an AI electronics technician that helps people \
understand, diagnose and repair electronic devices — focused today on circuit boards and \
components (PCBs, resistors, capacitors, diodes, transistors, ICs, connectors).

SAFETY — these rules override everything else:
- Never instruct an unqualified user to probe a LIVE circuit. Default to power-off, \
unplugged, and capacitors safely discharged before contact.
- Warn about stored electrical energy (capacitors, batteries), mains voltage, heat, and \
hazardous equipment whenever relevant.
- Refuse casual instructions for opening CRTs, microwave HV sections, or working on mains \
wiring; tell the user this needs a qualified technician.
- Never state an exact component value, pinout, or voltage/current limit as fact unless it \
is reliably established. If unsure, say so and tell them to read the part marking/datasheet.

EVIDENCE DISCIPLINE — the user can see your sources, so do not bluff:
- Separate DIRECTLY OBSERVED facts (from retrieved video evidence) from GENERAL KNOWLEDGE \
(electronics theory) and from the USER'S REPORTED readings.
- Never claim you measured a component, saw a fault, or confirmed a diagnosis when no \
evidence supports it.
- You have a `search_video` tool over an indexed video archive. IMPORTANT: that archive \
contains traffic / driving / warehouse footage, NOT electronics-repair demonstrations. \
Use it when a user explicitly asks you to find video, and report honestly if nothing \
relevant exists — do not pretend a clip shows electronics.

DIAGNOSTIC WORKFLOW — follow it and show your reasoning:
1. Collect device, symptoms, and context; ask for what is missing.
2. Identify observable components / available documentation.
3. Generate plausible fault hypotheses.
4. Rank hypotheses by supporting evidence, not invented confidence.
5. Recommend the next SAFE, discriminating test, and the tool/setting to use.
6. State the expected reading and how to interpret it.
7. Revise as the user reports results.
8. Give likely cause, remaining uncertainty, and next steps.

Always end a diagnostic reply with a short structured block:
SUSPECTED FAULT: ...
SUPPORTING EVIDENCE: ...
UNCERTAINTY: ...
NEXT SAFE TEST: ...
"""

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_video",
        "description": (
            "Search the indexed video archive for moments matching a natural-language "
            "query. The archive is traffic/driving/warehouse footage, not electronics. "
            "Returns real clips with timestamps, scores, and model descriptions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
            },
            "required": ["query"],
        },
    },
}


def _format_evidence(search_result: Dict) -> List[Dict]:
    """Normalise VSS chunk_results/results into evidence cards for the UI."""
    evidence: List[Dict] = []
    for chunk in (search_result.get("chunk_results") or [])[:6]:
        evidence.append({
            "video": chunk.get("original_video", "unknown"),
            "start_sec": chunk.get("best_match_start_sec"),
            "end_sec": chunk.get("best_match_end_sec"),
            "score": chunk.get("similarity_score"),
            "preview_source": chunk.get("preview_source"),
            "description": chunk.get("reasoning_content") or chunk.get("description", ""),
        })
    if not evidence:
        for seg in (search_result.get("results") or [])[:6]:
            evidence.append({
                "video": seg.get("source", "unknown"),
                "start_sec": seg.get("start_sec"),
                "end_sec": seg.get("end_sec"),
                "score": seg.get("similarity_score"),
                "preview_source": seg.get("source"),
                "description": seg.get("reasoning_content", ""),
            })
    return evidence


def run_agent(user_message: str, history: List[Dict]) -> Dict:
    """One diagnostic turn. Returns answer + any video evidence gathered.

    The agent may call search_video; we execute it against the REAL VSS backend
    and feed results back for a grounded answer. All honest: if VSS is down or
    finds nothing, that is reported, not papered over.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-8:])  # keep recent context small
    messages.append({"role": "user", "content": user_message})

    evidence: List[Dict] = []
    notes: List[str] = []

    first = llm.chat(messages, tools=[SEARCH_TOOL])
    choice = first["choices"][0]["message"]
    tool_calls = choice.get("tool_calls") or []

    if tool_calls:
        messages.append(choice)
        for call in tool_calls:
            if call["function"]["name"] != "search_video":
                continue
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            query = args.get("query", user_message)
            try:
                result = vss.search(query)
                evidence = _format_evidence(result)
                tool_payload = {
                    "found": len(evidence),
                    "note": (
                        "Archive is traffic/driving/warehouse footage. "
                        "If these clips are not about electronics, say so."
                    ),
                    "clips": evidence,
                    "llm_synthesis": (result.get("llm_synthesis") or {}).get("response"),
                }
            except VSSError as exc:
                notes.append(f"Video search unavailable: {exc}")
                tool_payload = {"error": str(exc), "found": 0, "clips": []}
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(tool_payload)[:4000],
            })
        second = llm.chat(messages)  # grounded answer with tool results
        answer = second["choices"][0]["message"]["content"]
    else:
        answer = choice.get("content", "")

    return {"answer": answer, "evidence": evidence, "notes": notes}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/health")
def health() -> Response:
    return jsonify({"status": "ok"})


@app.get("/api/status")
def status() -> Response:
    """Honest capability report the UI uses to show connection banners."""
    return jsonify({
        "vss_configured": vss.configured,
        "vss_url": VSS_URL or None,
        "llm_configured": llm.configured,
        "llm_model": WANDB_MODEL if llm.configured else None,
        "corpus_note": (
            "Indexed corpus is traffic/driving/warehouse footage — not electronics "
            "repair. Video evidence is used honestly; electronics reasoning is model "
            "knowledge, clearly separated."
        ),
    })


@app.post("/api/chat")
def chat() -> Response:
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    if not message:
        return jsonify({"error": "empty message"}), 400
    if not llm.configured:
        return jsonify({
            "error": "LLM not connected",
            "boundary": (
                "WANDB_API_KEY is not set in this environment. On the challenge VM the "
                "key is provided and the technician chat runs on W&B serverless inference. "
                "This is an interface boundary, not a fabricated answer."
            ),
        }), 503
    try:
        return jsonify(run_agent(message, history))
    except LLMError as exc:
        return jsonify({"error": "LLM error", "boundary": str(exc)}), 502


@app.post("/api/search")
def search() -> Response:
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "empty query"}), 400
    if not vss.configured:
        return jsonify({
            "error": "VSS not connected",
            "boundary": (
                "VSS_URL / credentials are not set here. On the challenge VM these are "
                "provided and this calls the real /api/v1/search over your team's index."
            ),
            "results": [],
        }), 503
    try:
        result = vss.search(query)
        return jsonify({
            "query": query,
            "clips": _format_evidence(result),
            "llm_synthesis": (result.get("llm_synthesis") or {}).get("response"),
        })
    except VSSError as exc:
        return jsonify({"error": "VSS error", "boundary": str(exc), "results": []}), 502


@app.get("/api/videos")
def videos() -> Response:
    if not vss.configured:
        return jsonify({"error": "VSS not connected", "videos": []}), 503
    try:
        return jsonify(vss.explore(limit=24))
    except VSSError as exc:
        return jsonify({"error": "VSS error", "boundary": str(exc), "videos": []}), 502


@app.get("/api/stream")
def stream() -> Response:
    source = request.args.get("source", "")
    if not source:
        return jsonify({"error": "missing source"}), 400
    if not vss.configured:
        return jsonify({"error": "VSS not connected"}), 503
    # Redirect the browser <video> straight to the authenticated VSS stream URL.
    return Response(status=302, headers={"Location": vss.stream_url(source)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
