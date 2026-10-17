"""VSS retrieval client. Credentials come from the environment only."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_VIDEO = "s3://team-14-vss-chunks/team-14/20261017_114908_dc702364.mp4"
# Pods cannot hairpin to the external ingress. The in-cluster retrieval Service is the fallback.
IN_CLUSTER_VSS = "http://video-backend-service:8000"
LOCATIONS = ("electronics-bench", "electronics-bench-nano")
QUERIES = ("arduino nano", "arduino")


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


class VssError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class VssClient:
    def __init__(self) -> None:
        self.base = _env("VSS_URL", "INGRESS_URL").rstrip("/")
        self.username = _env("VSS_USERNAME", "USERNAME")
        self.password = _env("VSS_PASSWORD", "PASSWORD")
        self._token = ""
        self._lock = threading.Lock()
        self._used_cluster = self.base.rstrip("/") == IN_CLUSTER_VSS

    def _switch_to_cluster(self) -> bool:
        if self._used_cluster:
            return False
        self._used_cluster = True
        self.base = IN_CLUSTER_VSS
        self._token = ""
        return True

    def _login(self) -> str:
        if not self.base or not self.username or not self.password:
            raise VssError("VSS credentials are not configured", 500)
        status, payload, _headers = self._raw(
            "POST",
            "/api/v1/auth/login",
            {"username": self.username, "password": self.password},
            auth=False,
        )
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if status != 200 or not token:
            raise VssError("VSS login failed", 502 if status != 401 else 401)
        self._token = token
        return token

    def token(self) -> str:
        with self._lock:
            if self._token:
                return self._token
            return self._login()

    def _raw(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        auth: bool = True,
        timeout: float = 60,
        range_header: str | None = None,
        stream: bool = False,
    ):
        data = None if body is None else json.dumps(body).encode()
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self.token() if path != '/api/v1/auth/login' else ''}"
        if range_header:
            headers["Range"] = range_header
        url = self.base + path
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        safe_path = path.split("?", 1)[0]
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            exc.read()
            if exc.code == 401 and auth:
                with self._lock:
                    self._token = ""
                    self._login()
                headers["Authorization"] = f"Bearer {self._token}"
                request = urllib.request.Request(url, data=data, headers=headers, method=method)
                try:
                    response = urllib.request.urlopen(request, timeout=timeout)
                except urllib.error.HTTPError as again:
                    again.read()
                    raise VssError(f"VSS {safe_path} returned {again.code}", again.code) from None
                except (urllib.error.URLError, TimeoutError, OSError):
                    if self._switch_to_cluster():
                        return self._raw(method, path, body, auth, timeout, range_header, stream)
                    raise VssError("VSS unreachable", 502) from None
            else:
                raise VssError(f"VSS {safe_path} returned {exc.code}", exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if self._switch_to_cluster():
                return self._raw(method, path, body, auth, timeout, range_header, stream)
            raise VssError("VSS unreachable", 502) from None
        if stream:
            return response
        raw = response.read()
        parsed: object
        if not raw:
            parsed = {}
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {}
        return response.status, parsed, dict(response.headers)

    def _search_one(self, location: str, query: str) -> list[dict]:
        _status, payload, _headers = self._raw(
            "POST",
            "/api/v1/search",
            {
                "query": query,
                "top_k": 20,
                "llm_top_n": 1,
                "min_similarity": 0.3,
                "metadata_filters": {"location": location},
                "include_public": True,
            },
            timeout=40,
        )
        if not isinstance(payload, dict):
            return []
        return [chunk for chunk in (payload.get("chunk_results") or []) if isinstance(chunk, dict)]

    def search_bench_clips(self) -> list[dict]:
        found: dict[str, dict] = {}
        jobs = [(location, query) for location in LOCATIONS for query in QUERIES]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self._search_one, location, query) for location, query in jobs]
            try:
                for future in as_completed(futures, timeout=50):
                    try:
                        chunks = future.result()
                    except (VssError, TimeoutError, OSError):
                        continue
                    self._absorb_chunks(found, chunks)
            except TimeoutError:
                pass
        if DEFAULT_VIDEO not in found:
            found[DEFAULT_VIDEO] = {
                "original_video": DEFAULT_VIDEO,
                "camera_id": "bench-cam-1",
                "location": "electronics-bench",
                "tags": ["arduino-nano", "led", "blink"],
                "duration_sec": 100,
                "score": 1,
                "filename": "",
            }
        clips = list(found.values())
        clips.sort(key=lambda item: (item["original_video"] != DEFAULT_VIDEO, -item["score"]))
        return clips

    def _absorb_chunks(self, found: dict[str, dict], chunks: list[dict]) -> None:
        for chunk in chunks:
            video = chunk.get("original_video")
            location = chunk.get("location")
            if not video or location not in LOCATIONS:
                continue
            score = float(chunk.get("similarity_score") or 0)
            current = found.get(video)
            if current and current["score"] >= score:
                continue
            total = int(chunk.get("total_segments") or 0)
            duration = float(total * 5) if total else float(chunk.get("chunk_duration_sec") or 0)
            tags = chunk.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            found[video] = {
                "original_video": video,
                "camera_id": chunk.get("camera_id") or "",
                "location": location,
                "tags": list(tags),
                "duration_sec": duration,
                "score": score,
                "filename": chunk.get("filename") or "",
            }

    def segments(self, original_video: str) -> list[dict]:
        query = urllib.parse.urlencode({"original_video": original_video})
        _status, payload, _headers = self._raw(
            "GET",
            f"/api/v1/tools/segments?{query}",
            timeout=90,
        )
        rows = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            tags = row.get("tags") or []
            if isinstance(tags, str):
                tags = [part.strip() for part in tags.split(",") if part.strip()]
            cleaned.append(
                {
                    "segment_number": int(row.get("segment_number") or 0),
                    "segment_start_sec": float(row.get("segment_start_sec") or 0),
                    "segment_end_sec": float(
                        row.get("segment_end_sec")
                        or (float(row.get("segment_start_sec") or 0) + float(row.get("duration") or 5))
                    ),
                    "reasoning_content": row.get("reasoning_content") or "",
                    "source": row.get("source") or "",
                    "object_classes": row.get("object_classes") or "",
                    "camera_id": row.get("camera_id") or "",
                    "location": row.get("location") or "",
                    "tags": list(tags),
                }
            )
        cleaned.sort(key=lambda item: item["segment_number"])
        return cleaned

    def ask(self, question: str, original_video: str) -> dict:
        _status, payload, _headers = self._raw(
            "POST",
            "/api/v1/agent/ask",
            {"question": question, "original_video": original_video, "top_k": 20},
            timeout=50,
        )
        if not isinstance(payload, dict):
            return {"answer": "", "tool_used": "", "evidence": {}}
        return {
            "answer": payload.get("answer") or "",
            "tool_used": payload.get("tool_used") or "",
            "evidence": payload.get("evidence") or {},
        }

    def open_stream(self, source: str, range_header: str | None):
        """Proxy /api/v1/videos/stream. Parent original_video URIs return playable MP4 bytes."""
        if not source.startswith("s3://"):
            raise VssError("source must be an s3 uri", 400)

        def once(token: str):
            query = urllib.parse.urlencode({"source": source, "token": token})
            return self._raw(
                "GET",
                f"/api/v1/videos/stream?{query}",
                auth=False,
                timeout=120,
                range_header=range_header,
                stream=True,
            )

        try:
            return once(self.token())
        except VssError as exc:
            if exc.status != 401:
                raise
            with self._lock:
                self._token = ""
                fresh = self._login()
            return once(fresh)
