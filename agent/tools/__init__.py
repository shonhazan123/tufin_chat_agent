"""Tool autodiscovery — imports every .py in this package at startup.

The @registry.register(...) decorators fire on import, populating the
AgentRegistry before llm_system_prompts builds the planner prompt.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SKIP_MODULES = {"__init__", "tool_base_classes"}


def discover_tools() -> None:
    """Import all tool modules in this directory (excluding tool_base_classes and __init__)."""
    package_dir = Path(__file__).resolve().parent
    for path in sorted(package_dir.glob("*.py")):
        module_name = path.stem
        if module_name in _SKIP_MODULES:
            continue
        fully_qualified_module_name = f"agent.tools.{module_name}"
        try:
            importlib.import_module(fully_qualified_module_name)
            logger.info("Autodiscovered tool module: %s", fully_qualified_module_name)
        except Exception:
            logger.exception("Failed to import tool module: %s", fully_qualified_module_name)
