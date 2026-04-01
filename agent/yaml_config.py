"""YAML configuration loader with env var resolution and singleton caching."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

_ENV_PATTERN = re.compile(r"\$\{(\w+)(?::-(.*?))?\}")

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_SHARED_PATH = _CONFIG_DIR / "shared.yaml"
_PROVIDER_FILES = {
    "openai": _CONFIG_DIR / "openai.yaml",
    "ollama": _CONFIG_DIR / "ollama.yaml",
}


def _resolve_env_vars(value: Any) -> Any:
    """Recursively resolve ${VAR:-default} patterns in config values."""
    if isinstance(value, str):

        def _replacer(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default)

        return _ENV_PATTERN.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override into base; nested dicts are merged, override wins on leaf keys."""
    out: dict[str, Any] = dict(base)
    for key, val in override.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping at root of {path}")
    return raw


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Load config/shared.yaml merged with config/openai.yaml or config/ollama.yaml.

    Provider is chosen at process startup via LLM_PROVIDER (default: openai).
    Uses @lru_cache so the merge runs once per process.
    Call load_dotenv() before first use so .env values are available.
    """
    load_dotenv()

    provider = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
    if provider not in _PROVIDER_FILES:
        allowed = ", ".join(sorted(_PROVIDER_FILES))
        raise ValueError(
            f"LLM_PROVIDER must be one of ({allowed}), got {provider!r}"
        )

    provider_path = _PROVIDER_FILES[provider]
    if not _SHARED_PATH.is_file():
        raise FileNotFoundError(f"Missing shared config: {_SHARED_PATH}")
    if not provider_path.is_file():
        raise FileNotFoundError(f"Missing provider config: {provider_path}")

    shared = _resolve_env_vars(_load_yaml(_SHARED_PATH))
    overlay = _resolve_env_vars(_load_yaml(provider_path))
    merged = _deep_merge(shared, overlay)
    return merged
