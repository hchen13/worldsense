"""
WorldSense system settings — persisted to ~/.worldsense/settings.json.

Three categories:
- General: defaults for language, sample size, country
- LLM: provider, model, api key, endpoint, concurrency, timeout, retries, token budget
- Advanced: temperature, debug mode, export format, result retention

Multi-Profile LLM:
- llm_profiles: list of named LLM configurations (model/endpoint/api_key/provider)
- active_profile: name of the currently active profile
- Backward-compatible: old single-llm format auto-migrates to a profile named "Default"
- env-var fallback: if no profiles exist, creates one named "Default" from env vars
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


SETTINGS_PATH = Path(os.path.expanduser("~/.worldsense/settings.json"))


class GeneralSettings(BaseModel):
    default_language: str = "English"
    default_sample_size: int = Field(default=50, ge=1, le=10000)
    default_country: str = ""  # empty = use market


class LLMSettings(BaseModel):
    """Legacy single-config block. Still used for concurrency/timeout/retry/token_budget."""
    provider: str = "openai"  # openai | anthropic | custom
    model: str = ""            # empty = use WS_MODEL env
    api_key: str = ""          # empty = use WS_API_KEY env
    endpoint: str = ""         # empty = use WS_API_BASE_URL env
    concurrency_limit: int = Field(default=10, ge=1, le=500)
    request_timeout: int = Field(default=120, ge=5, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    token_budget_per_task: int = Field(default=0, ge=0)  # 0 = unlimited


class LLMProfile(BaseModel):
    """A named LLM configuration profile."""
    name: str
    provider: str = "openai"
    model: str = ""
    api_key: str = ""
    endpoint: str = ""
    supports_vision: Optional[bool] = None  # None = not probed yet


class AdvancedSettings(BaseModel):
    temperature: float = Field(default=0.9, ge=0.0, le=2.0)
    debug_mode: bool = False
    default_export_format: str = "json"  # json | csv
    result_retention_days: int = Field(default=90, ge=1, le=3650)


class SystemSettings(BaseModel):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    advanced: AdvancedSettings = Field(default_factory=AdvancedSettings)
    # Multi-profile additions
    llm_profiles: list[LLMProfile] = Field(default_factory=list)
    active_profile: str = ""   # name of active profile; "" = use first profile


_cached: Optional[SystemSettings] = None


def _build_default_profile_from_env() -> LLMProfile:
    """Create a Default profile from env vars (WS_MODEL / WS_API_BASE_URL / WS_API_KEY)."""
    return LLMProfile(
        name="Default",
        provider="openai",
        model=os.getenv("WS_MODEL", ""),
        api_key=os.getenv("WS_API_KEY", ""),
        endpoint=os.getenv("WS_API_BASE_URL", ""),
    )


def _migrate_legacy_llm(data: dict) -> dict:
    """
    Backward-compat migration: if llm_profiles is absent but llm block has model/key/endpoint,
    promote the llm block to a profile named 'Default'.
    """
    if "llm_profiles" in data:
        return data  # already migrated

    llm = data.get("llm", {})
    has_credentials = any([llm.get("model"), llm.get("api_key"), llm.get("endpoint")])
    if has_credentials:
        profile = {
            "name": "Default",
            "provider": llm.get("provider", "openai"),
            "model": llm.get("model", ""),
            "api_key": llm.get("api_key", ""),
            "endpoint": llm.get("endpoint", ""),
            "supports_vision": llm.get("supports_vision", None),
        }
        data["llm_profiles"] = [profile]
        data["active_profile"] = "Default"
    else:
        data["llm_profiles"] = []
        data["active_profile"] = ""

    return data


def load_settings() -> SystemSettings:
    """Load settings from disk, falling back to defaults. Auto-migrates legacy format."""
    global _cached
    if _cached is not None:
        return _cached
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text())
            data = _migrate_legacy_llm(data)
            _cached = SystemSettings.model_validate(data)
            return _cached
        except Exception:
            pass
    _cached = SystemSettings()
    return _cached


def save_settings(settings: SystemSettings) -> None:
    """Persist settings to disk and update cache."""
    global _cached
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(settings.model_dump_json(indent=2))
    _cached = settings


def invalidate_cache() -> None:
    global _cached
    _cached = None


def get_active_profile(settings: Optional[SystemSettings] = None) -> LLMProfile:
    """
    Return the active LLM profile, creating an env-var based default if none exist.
    """
    if settings is None:
        settings = load_settings()

    profiles = settings.llm_profiles

    if not profiles:
        return _build_default_profile_from_env()

    # Find by name
    if settings.active_profile:
        for p in profiles:
            if p.name == settings.active_profile:
                return p

    # Fallback: first profile
    return profiles[0]
