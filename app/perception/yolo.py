"""YOLO11 change detection + bboxes — gate for Cosmos (COCO classes)."""
from __future__ import annotations

import base64
import hashlib
import json
import logging

import aiohttp

from config import settings
from timing import timed

log = logging.getLogger("yolo")

# COCO labels that mean "this is probably a person selfie, not a breadboard"
PERSON_LIKE = {"person", "cat", "dog", "bird", "horse", "cow", "sheep", "bear", "zebra", "giraffe"}
# Weak desk/electronics-adjacent COCO cues (YOLO has no breadboard/arduino class)
BENCH_HINTS = {
    "laptop", "keyboard", "mouse", "remote", "cell phone", "tv", "monitor",
    "scissors", "book", "clock", "bottle", "cup", "fork", "knife", "spoon",
}


async def infer_frame(session: aiohttp.ClientSession, jpeg: bytes) -> dict:
    """Run YOLO via video_base64 (API rejects image_base64). Fallback: phash only."""
    if not settings.gpu_token or not settings.yolo_url:
        return _hash_only(jpeg, ok=False, error="no_yolo_config")

    # Hackathon YOLO InferRequest: exactly one of url | video_base64
    body = {
        "video_base64": base64.b64encode(jpeg).decode(),
        "filename": "frame.jpg",
        "include_frames": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.gpu_token}",
        "Content-Type": "application/json",
    }
    url = settings.yolo_url.rstrip("/") + "/v1/infer"
    with timed("yolo") as t:
        try:
            async with session.post(
                url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                raw = await resp.read()
                if resp.status >= 400:
                    log.warning("yolo_http=%s body=%s", resp.status, raw[:200])
                    return {
                        **_hash_only(jpeg, ok=False, error=f"http_{resp.status}"),
                        "ms": t["ms"],
                        "http": resp.status,
                    }
                data = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            log.warning("yolo_error=%s", type(e).__name__)
            return {**_hash_only(jpeg, ok=False, error=type(e).__name__), "ms": t.get("ms")}

    boxes, labels, shape = _parse_detections(data)
    classes = data.get("object_classes") or labels
    if isinstance(classes, str):
        classes = [x.strip() for x in classes.split(",") if x.strip()]
    labels = [str(x) for x in (classes or labels)]
    sig = hashlib.sha1(
        (",".join(sorted(labels)) + "|" + json.dumps(boxes, sort_keys=True)[:200]).encode()
    ).hexdigest()[:16]
    gate = scene_gate(labels, boxes, shape)
    return {
        "signature": sig,
        "labels": labels,
        "boxes": boxes,
        "shape": shape,
        "ms": t["ms"],
        "ok": bool(data.get("ok") or data.get("perception_ok")),
        "max_conf": data.get("max_detection_conf"),
        "gate": gate,
        "counts": data.get("object_counts") or {},
    }


def _parse_detections(data: dict) -> tuple[list[dict], list[str], list[int] | None]:
    boxes: list[dict] = []
    labels: list[str] = []
    shape = None
    frames = data.get("frames") or []
    if not frames and isinstance(data.get("perception_json"), dict):
        frames = data["perception_json"].get("frames") or []
    if frames and isinstance(frames[0], dict):
        shape = frames[0].get("shape")
        for det in frames[0].get("detections") or []:
            if not isinstance(det, dict):
                continue
            lab = str(det.get("label") or det.get("class") or det.get("name") or "")
            bbox = det.get("bbox") or det.get("box") or det.get("xyxy")
            conf = float(det.get("confidence") or det.get("conf") or 0)
            if lab:
                labels.append(lab)
            if bbox and len(bbox) >= 4:
                x1, y1, x2, y2 = [float(bbox[i]) for i in range(4)]
                boxes.append({
                    "label": lab or "obj",
                    "confidence": round(conf, 3),
                    "xyxy": [x1, y1, x2, y2],
                })
    if not labels:
        for key in ("detections", "objects", "classes", "results"):
            items = data.get(key)
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, str):
                        labels.append(it)
                    elif isinstance(it, dict):
                        lab = it.get("label") or it.get("class") or it.get("name")
                        if lab:
                            labels.append(str(lab))
    if not labels and isinstance(data.get("object_classes"), list):
        labels = [str(x) for x in data["object_classes"]]
    return boxes, labels, shape


def scene_gate(labels: list[str], boxes: list[dict], shape: list | None) -> dict:
    """
    Decide whether this frame is worth a Cosmos call.
    YOLO is COCO — it cannot name breadboards; we reject person-dominant / selfie frames.
    """
    low = {str(l).lower() for l in labels}
    personish = sorted(low & PERSON_LIKE)
    hints = sorted(low & BENCH_HINTS)

    h = w = None
    if shape and len(shape) >= 2:
        # YOLO shape observed as [height, width]
        h, w = float(shape[0]), float(shape[1])
    area = (h * w) if h and w else None

    person_frac = 0.0
    if area and boxes:
        for b in boxes:
            if str(b.get("label", "")).lower() in PERSON_LIKE:
                x1, y1, x2, y2 = b["xyxy"]
                person_frac = max(person_frac, max(0.0, (x2 - x1) * (y2 - y1)) / area)

    # Hard reject: person/animal fills a large part of the frame
    if person_frac >= 0.28 or (personish and not hints and person_frac >= 0.12):
        return {
            "allow_cosmos": False,
            "reason": "person_or_animal_in_frame",
            "detail": f"YOLO sees {personish or labels}; point the camera at the breadboard.",
            "person_frac": round(person_frac, 3),
            "hints": hints,
        }

    # Empty COCO detections: could be a close-up breadboard (not in COCO) — allow Cosmos
    if not labels:
        return {
            "allow_cosmos": True,
            "reason": "no_coco_objects_possible_bench",
            "detail": "No COCO objects; treating as possible close-up bench.",
            "person_frac": round(person_frac, 3),
            "hints": hints,
        }

    if hints and not personish:
        return {
            "allow_cosmos": True,
            "reason": "desk_hints",
            "detail": f"Desk-like cues: {hints}",
            "person_frac": round(person_frac, 3),
            "hints": hints,
        }

    if personish and hints and person_frac < 0.2:
        return {
            "allow_cosmos": True,
            "reason": "mixed_desk_ok",
            "detail": "Person small + desk objects present.",
            "person_frac": round(person_frac, 3),
            "hints": hints,
        }

    # Random COCO junk (e.g. 'cat' on a jacket) with no desk cues → skip
    return {
        "allow_cosmos": False,
        "reason": "irrelevant_coco",
        "detail": f"YOLO classes {sorted(low)} are not a breadboard scene.",
        "person_frac": round(person_frac, 3),
        "hints": hints,
    }


def _hash_only(jpeg: bytes, *, ok: bool, error: str | None = None) -> dict:
    return {
        "signature": hashlib.sha1(jpeg[:: max(1, len(jpeg) // 256)]).hexdigest()[:16],
        "labels": [],
        "boxes": [],
        "shape": None,
        "ms": 0,
        "ok": ok,
        "error": error,
        "gate": {
            "allow_cosmos": False,
            "reason": "yolo_unavailable",
            "detail": error or "yolo failed — not calling Cosmos on hash-only motion",
            "person_frac": 0.0,
            "hints": [],
        },
    }


def changed(prev: str | None, cur: str) -> bool:
    if prev is None:
        return True
    return prev != cur
