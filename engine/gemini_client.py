"""Gemini API client wrapper for Proofit matching engine and normalizers.

Provides structured JSON generation with Pydantic models via response_schema,
text embeddings via Google Gemini embeddings (768 dimensions), and text generation.
Supports google.genai and legacy google.generativeai SDKs with offline deterministic fallback
and dynamic model fallback when rate limits or quotas (429) are reached.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import time
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)


# Type variable for Pydantic schema return
T = TypeVar("T", bound=BaseModel)

_GENAI_NEW = importlib.util.find_spec("google.genai") is not None
_GENAI_LEGACY = importlib.util.find_spec("google.generativeai") is not None

# Preferred fallback sequence when a model hits free-tier rate limits (e.g., 429 RESOURCE_EXHAUSTED)
FALLBACK_MODELS = [
    "gemini-3.1-flash-lite",
]

# Map legacy / rate-limited endpoint aliases to live high-capacity models
_MODEL_MAP = {
    "gemini-3.6-flash": "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite": "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite": "gemini-3.1-flash-lite",
    "gemini-2.5-flash": "gemini-3.1-flash-lite",
    "gemini-2.5-pro": "gemini-3.1-flash-lite",
    "gemini-2.0-flash": "gemini-3.1-flash-lite",
    "gemini-1.5-pro": "gemini-3.1-flash-lite",
    "gemini-1.5-flash": "gemini-3.1-flash-lite",
}


def get_gemini_api_key() -> str | None:
    """Retrieve GEMINI_API_KEY from environment."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")



def get_default_gemini_model() -> str:
    """Retrieve default preferred Gemini model name."""
    return os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")


def get_extract_model() -> str:
    """Retrieve preferred model name for Ingest & Schema Normalization."""
    return os.getenv("GEMINI_EXTRACT_MODEL") or get_default_gemini_model()


def get_analysis_model() -> str:
    """Retrieve preferred model name for Fit Analysis & Bullet Rewriter."""
    return os.getenv("GEMINI_ANALYSIS_MODEL") or get_default_gemini_model()


def _get_eff_timeout(timeout: float | None = None) -> float:
    if timeout is not None:
        return max(0.05, float(timeout))
    try:
        from api.config import settings
        return max(0.05, float(settings.external_call_timeout_seconds))
    except Exception:
        return float(os.getenv("EXTERNAL_CALL_TIMEOUT_SECONDS", "25.0"))


def _remaining_timeout(deadline: float) -> float:
    """Use one wall-clock budget across SDKs and model fallbacks."""
    remaining = deadline - time.monotonic()
    if remaining < 0.001:
        raise TimeoutError("Gemini request exceeded its time budget.")
    return remaining


def generate_structured_json(  # noqa: UP047
    prompt: str,
    response_schema: type[T],
    model_name: str | None = None,
    temperature: float = 0.0,
    system_instruction: str | None = None,
    thinking_budget: int | None = None,
    timeout: float | None = None,
) -> T:
    """Generate structured JSON matching a Pydantic schema using Gemini API.

    Automatically retries with fallback models if the primary model hits rate limits or quota caps.
    Enforces deadlines and socket/network timeouts at the SDK level with bounded retry attempts.
    Supports thinking_budget parameter (e.g. 0 to disable reasoning overhead during extraction).
    Falls back to RuntimeError if GEMINI_API_KEY is not configured or in offline mode.
    """
    api_key = get_gemini_api_key()

    if api_key and os.getenv("ENGINE_MODE") != "mock":
        eff_timeout = _get_eff_timeout(timeout)
        deadline = time.monotonic() + eff_timeout
        preferred = model_name or get_default_gemini_model()

        # Build candidate list with bounded retries (at most preferred + 1 fallback)
        candidates: list[str] = [preferred]
        for fb in FALLBACK_MODELS:
            if fb not in candidates and fb != preferred:
                candidates.append(fb)
                if len(candidates) >= 2:
                    break

        for candidate in candidates:
            _remaining_timeout(deadline)
            target_model = _MODEL_MAP.get(candidate, candidate)

            # 1. Prefer modern google.genai SDK
            if _GENAI_NEW:
                try:
                    from google import genai
                    from google.genai import types

                    client = genai.Client(
                        api_key=api_key,
                        http_options=types.HttpOptions(
                            timeout=int(_remaining_timeout(deadline) * 1000),
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    )
                    config: dict = {
                        "response_mime_type": "application/json",
                        "response_schema": response_schema,
                        "temperature": temperature,
                    }
                    if system_instruction:
                        config["system_instruction"] = system_instruction
                    if thinking_budget is not None and thinking_budget > 0:
                        config["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

                    response = client.models.generate_content(
                        model=target_model,
                        contents=prompt,
                        config=config,
                    )
                    if response and response.text:
                        return response_schema.model_validate_json(response.text)
                except Exception as err:
                    logger.warning("google.genai call for %s failed (%s). Trying fallback.", target_model, err)

            # 2. Fall back to google.generativeai if available
            if _GENAI_LEGACY:
                _remaining_timeout(deadline)
                try:
                    import google.generativeai as genai  # noqa: F401

                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        model_name=target_model,
                        generation_config={
                            "response_mime_type": "application/json",
                            "response_schema": response_schema,
                            "temperature": temperature,
                        },
                        system_instruction=system_instruction,
                    )
                    response = model.generate_content(
                        prompt,
                        request_options={"timeout": _remaining_timeout(deadline), "retry": None},
                    )
                    if response and response.text:
                        return response_schema.model_validate_json(response.text)
                except TimeoutError:
                    raise
                except Exception as err:
                    logger.warning("google.generativeai call for %s failed (%s). Trying fallback.", target_model, err)

        _remaining_timeout(deadline)

    raise RuntimeError(
        f"Gemini API unavailable or invalid configuration for prompt: {prompt[:50]}... "
        "Provide GEMINI_API_KEY or use ENGINE_MODE=mock."
    )


def generate_gemini_text(
    prompt: str,
    json_mode: bool = False,
    model_name: str | None = None,
    temperature: float = 0.0,
    system_instruction: str | None = None,
    thinking_budget: int | None = None,
    timeout: float | None = None,
) -> str:
    """Generate text output using Gemini API with automatic model fallback."""
    api_key = get_gemini_api_key()

    if api_key and os.getenv("ENGINE_MODE") != "mock":
        eff_timeout = _get_eff_timeout(timeout)
        deadline = time.monotonic() + eff_timeout
        preferred = model_name or get_default_gemini_model()

        candidates: list[str] = [preferred]
        for fb in FALLBACK_MODELS:
            if fb not in candidates and fb != preferred:
                candidates.append(fb)
                if len(candidates) >= 2:
                    break

        for candidate in candidates:
            _remaining_timeout(deadline)
            target_model = _MODEL_MAP.get(candidate, candidate)

            if _GENAI_NEW:
                try:
                    from google import genai
                    from google.genai import types

                    client = genai.Client(
                        api_key=api_key,
                        http_options=types.HttpOptions(
                            timeout=int(_remaining_timeout(deadline) * 1000),
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    )
                    config: dict = {"temperature": temperature}
                    if json_mode:
                        config["response_mime_type"] = "application/json"
                    if system_instruction:
                        config["system_instruction"] = system_instruction
                    if thinking_budget is not None and thinking_budget > 0:
                        config["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

                    response = client.models.generate_content(
                        model=target_model,
                        contents=prompt,
                        config=config,
                    )
                    if response and response.text:
                        return response.text
                except Exception as err:
                    logger.warning("google.genai text call for %s failed (%s). Trying fallback.", target_model, err)

            if _GENAI_LEGACY:
                _remaining_timeout(deadline)
                try:
                    import google.generativeai as genai  # noqa: F401

                    genai.configure(api_key=api_key)
                    gen_config: dict = {"temperature": temperature}
                    if json_mode:
                        gen_config["response_mime_type"] = "application/json"
                    model = genai.GenerativeModel(
                        model_name=target_model,
                        generation_config=gen_config,
                        system_instruction=system_instruction,
                    )
                    response = model.generate_content(
                        prompt,
                        request_options={"timeout": _remaining_timeout(deadline), "retry": None},
                    )
                    if response and response.text:
                        return response.text
                except TimeoutError:
                    raise
                except Exception as err:
                    logger.warning("google.generativeai text call for %s failed (%s). Trying fallback.", target_model, err)

        _remaining_timeout(deadline)

    raise RuntimeError(
        f"Gemini API unavailable or invalid configuration for prompt: {prompt[:50]}... "
        "Provide GEMINI_API_KEY or use ENGINE_MODE=mock."
    )


def get_embedding(
    text: str,
    model_name: str = "gemini-embedding-001",
    timeout: float | None = None,
) -> list[float]:
    """Generate text embedding vector using Gemini (768 dims)."""
    api_key = get_gemini_api_key()
    if api_key and os.getenv("ENGINE_MODE") != "mock":
        eff_timeout = _get_eff_timeout(timeout)
        deadline = time.monotonic() + eff_timeout
        # 1. Prefer modern google.genai SDK
        if _GENAI_NEW:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(
                        timeout=int(_remaining_timeout(deadline) * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
                target_model = "gemini-embedding-001" if "text-embedding" in model_name else model_name
                response = client.models.embed_content(
                    model=target_model,
                    contents=text,
                    config={"output_dimensionality": 768},
                )
                if response and response.embeddings and len(response.embeddings) > 0:
                    return list(response.embeddings[0].values)
            except Exception as err:
                logger.warning("google.genai embedding call failed (%s).", err)

        # 2. Fall back to legacy SDK
        if _GENAI_LEGACY:
            _remaining_timeout(deadline)
            try:
                import google.generativeai as genai  # noqa: F401

                genai.configure(api_key=api_key)
                result = genai.embed_content(
                    model="models/gemini-embedding-001",
                    content=text,
                    output_dimensionality=768,
                    request_options={"timeout": _remaining_timeout(deadline), "retry": None},
                )
                if isinstance(result, dict) and "embedding" in result:
                    return list(result["embedding"])
            except TimeoutError:
                raise
            except Exception as err:
                logger.warning("Gemini embedding call failed (%s).", err)

        _remaining_timeout(deadline)

    # Deterministic fallback vector for offline testing (768 dimensions)
    seed_hash = hashlib.sha256(text.encode("utf-8")).digest()
    vector = []
    for i in range(768):
        byte_val = seed_hash[i % len(seed_hash)]
        val = (byte_val / 127.5) - 1.0
        vector.append(round(val, 6))
    return vector

