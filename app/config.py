"""Env-only configuration. Never log secret values."""
from __future__ import annotations

import os


def _req(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"missing env {name}")
    return v


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


class Settings:
    def __init__(self) -> None:
        self.port = int(_opt("PORT", "8080"))
        self.gpu_token = _opt("GPU_BEARER_TOKEN")
        self.cosmos_url = _opt("COSMOS3_REASON_URL", "http://166.19.38.112:8001").rstrip("/")
        self.yolo_url = _opt("YOLO_URL", "http://166.19.38.112:8002").rstrip("/")
        self.embed_url = _opt("COSMOS_EMBED1_URL", "http://166.19.38.112:8003").rstrip("/")
        self.canary_url = _opt("CANARY_1B_URL", "http://166.19.38.112:8004").rstrip("/")
        self.canary_model = _opt("CANARY_MODEL", "")
        self.vss_url = _opt("VSS_URL", "").rstrip("/")
        self.vss_user = _opt("VSS_USERNAME")
        self.vss_password = _opt("VSS_PASSWORD")
        self.wandb_key = _opt("WANDB_API_KEY")
        self.wandb_team = _opt("WANDB_TEAM")
        self.wandb_project = _opt("WANDB_PROJECT")
        self.wandb_base = _opt("WANDB_INFERENCE_URL", "https://api.inference.wandb.ai/v1").rstrip("/")
        self.s3_endpoint = _opt("S3_ENDPOINT").rstrip("/")
        self.s3_access_key = _opt("ACCESS_KEY")
        self.s3_secret_key = _opt("SECRET_KEY")
        self.s3_bucket = _opt("S3_CHUNKS_BUCKET")
        self.vdb_endpoint = _opt("VDB_ENDPOINT") or self.s3_endpoint
        self.vdb_schema = _opt("VDB_SCHEMA")
        self.embed_model = _opt("COSMOS_EMBED1_MODEL")
        self.supply_voltage = float(_opt("SUPPLY_VOLTAGE", "5.0"))
        self.cosmos_p95_degraded_s = float(_opt("COSMOS_P95_DEGRADED_S", "8.0"))
        self.heartbeat_s = float(_opt("HEARTBEAT_S", "5.0"))
        self.guidance_cooldown_s = float(_opt("GUIDANCE_COOLDOWN_S", "8.0"))

    @property
    def gpu_ready(self) -> bool:
        return bool(self.gpu_token and self.cosmos_url)

    @property
    def s3_ready(self) -> bool:
        return bool(self.s3_endpoint and self.s3_access_key and self.s3_secret_key and self.s3_bucket)

    @property
    def vss_ready(self) -> bool:
        return bool(self.vss_url and self.vss_user and self.vss_password)

    @property
    def wandb_ready(self) -> bool:
        return bool(self.wandb_key and self.wandb_team and self.wandb_project)


settings = Settings()
