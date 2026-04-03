"""Warmup orchestrator — wait for model availability, then prime the KV cache."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from agent.config_loader import load_config
from agent.llm_provider_factory import build_llm
from app.warmup.status import ModelStatus, model_state

logger = logging.getLogger(__name__)

MODEL_POLL_INTERVAL_S = 10
MODEL_POLL_TIMEOUT_S = 600
WARMUP_ATTEMPTS = 3
WARMUP_RETRY_DELAY_S = 3


async def _wait_for_model(base_url: str, model: str) -> None:
    """Poll Ollama /api/tags until *model* appears in the local model list."""
    tags_url = base_url.replace("/v1", "").rstrip("/") + "/api/tags"
    deadline = time.monotonic() + MODEL_POLL_TIMEOUT_S

    model_state.set(ModelStatus.DOWNLOADING, f"Waiting for {model}")
    logger.info("Polling %s for model '%s' (timeout %ds)", tags_url, model, MODEL_POLL_TIMEOUT_S)

    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(tags_url, timeout=5)
                if resp.status_code == 200:
                    available = [m["name"] for m in resp.json().get("models", [])]
                    if any(model in name for name in available):
                        logger.info("Model '%s' found in Ollama", model)
                        return
                    logger.info(
                        "Model '%s' not available yet (have: %s), retrying in %ds",
                        model, available, MODEL_POLL_INTERVAL_S,
                    )
            except Exception as exc:
                logger.info("Ollama not reachable: %s, retrying in %ds", exc, MODEL_POLL_INTERVAL_S)
            await asyncio.sleep(MODEL_POLL_INTERVAL_S)

    raise RuntimeError(
        f"Model '{model}' not available after {MODEL_POLL_TIMEOUT_S}s"
    )


async def _invoke_warmup() -> None:
    """Send a cheap prompt to pre-fill the KV cache. Model must already be present."""
    model_state.set(ModelStatus.WARMING_UP, "Sending warmup prompt")
    llm = build_llm("planner")

    for attempt in range(1, WARMUP_ATTEMPTS + 1):
        start = time.perf_counter()
        try:
            response = await llm.ainvoke("Reply with one word: ready")
            elapsed_ms = (time.perf_counter() - start) * 1000

            usage = getattr(response, "usage_metadata", None) or {}
            prompt_tokens = usage.get("input_tokens", "N/A")
            completion_tokens = usage.get("output_tokens", "N/A")

            logger.info(
                "Warmup %d/%d succeeded — %.0f ms | prompt_tokens=%s | completion_tokens=%s",
                attempt, WARMUP_ATTEMPTS, elapsed_ms, prompt_tokens, completion_tokens,
            )
            return
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "Warmup %d/%d failed — %.0f ms | error=%s",
                attempt, WARMUP_ATTEMPTS, elapsed_ms, exc,
            )
            if attempt < WARMUP_ATTEMPTS:
                await asyncio.sleep(WARMUP_RETRY_DELAY_S)

    raise RuntimeError(f"Warmup failed after {WARMUP_ATTEMPTS} attempts")


async def warmup_model() -> None:
    """Full lifecycle: skip for non-Ollama, wait for model, then warm up.

    Sets *model_state* at each stage so the UI can poll /health/model.
    On failure, sets ERROR status and re-raises so the caller decides
    whether to let the app continue.
    """
    cfg = load_config()
    if cfg["provider"] != "ollama":
        model_state.set(ModelStatus.SKIPPED, f"Provider is {cfg['provider']}")
        logger.info("Warmup skipped — provider is %s", cfg["provider"])
        return

    base_url = cfg["ollama"]["base_url"]
    model = cfg["agents"]["planner"]["model"]

    try:
        await _wait_for_model(base_url, model)
        await _invoke_warmup()
        model_state.set(ModelStatus.READY, "Model loaded and warm")
        logger.info("Model ready")
    except Exception as exc:
        model_state.set(ModelStatus.ERROR, str(exc))
        raise
