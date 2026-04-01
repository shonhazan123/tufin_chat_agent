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
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


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


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Load config.yaml, resolve env vars, return frozen dict structure.

    Uses @lru_cache so the file is read exactly once per process.
    Call load_dotenv() before this to ensure .env values are available.
    """
    load_dotenv()

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return _resolve_env_vars(raw)
