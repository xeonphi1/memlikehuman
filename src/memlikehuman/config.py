"""Local configuration contains environment-variable names, never API secrets."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from .models import Model


def default_data_dir() -> Path:
    return Path(os.environ.get("MEMLIKEHUMAN_HOME", Path.home() / ".local/share/memlikehuman"))


class ProviderConfig(Model):
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    api_key_env: str = "MEMLIKEHUMAN_API_KEY"
    version: str = "1"
    timeout_seconds: float = Field(default=30, ge=1, le=300)

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        url = urlparse(value)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ValueError("base_url must be an http(s) URL")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Do not place credentials, query strings or fragments in base_url")
        return value.rstrip("/")

    @field_validator("api_key_env")
    @classmethod
    def env_name(cls, value: str) -> str:
        if not value.isidentifier() or not value.isascii():
            raise ValueError("api_key_env must be an environment-variable name, not a key")
        return value


class Settings(Model):
    extraction: ProviderConfig | None = None
    embedding: ProviderConfig | None = None
    emotion_half_life_hours: float = Field(default=6, gt=0, le=8760)
    memory_half_life_days: float = Field(default=180, gt=0, le=36500)
    gist_after_days: float = Field(default=180, gt=0, le=36500)
    distant_after_days: float = Field(default=730, gt=0, le=36500)
    retrieval_candidates: int = Field(default=200, ge=100, le=400)
    semantic_scan_limit: int = Field(default=2000, ge=100, le=10000)

    @model_validator(mode="after")
    def ordered_ages(self):
        if self.distant_after_days < self.gist_after_days:
            raise ValueError("distant_after_days must be at least gist_after_days")
        return self

    @classmethod
    def load(cls, data_dir: Path) -> "Settings":
        path = data_dir / "config.json"
        return cls.model_validate_json(path.read_text()) if path.exists() else cls()

    def save(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = data_dir / "config.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.model_dump(), ensure_ascii=False, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(target)
