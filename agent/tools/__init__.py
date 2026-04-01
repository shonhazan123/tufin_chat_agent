"""Tool autodiscovery — imports every .py in this package at startup.

The @registry.register(SPEC) decorators fire on import, populating the
AgentRegistry before prompts.py builds PLANNER_SYSTEM.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SKIP = {"__init__", "base"}


def discover_tools() -> None:
    """Import all tool modules in this directory (excluding base and __init__)."""
    package_dir = Path(__file__).resolve().parent
    for path in sorted(package_dir.glob("*.py")):
        module_name = path.stem
        if module_name in _SKIP:
            continue
        fqn = f"agent.tools.{module_name}"
        try:
            importlib.import_module(fqn)
            logger.info("Autodiscovered tool module: %s", fqn)
        except Exception:
            logger.exception("Failed to import tool module: %s", fqn)
