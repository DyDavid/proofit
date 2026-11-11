"""Thin Gemini wrapper shared by detect/generate/validate.

One structured-output helper (`call_structured`) backs all three LLM call
sites: it asks the model for a JSON object that matches a JSON Schema, so the
response is a validated object, never prose to regex out of a message. Every
call site owns its own prompt and schema (`engine/rewrite/prompts.py`); this
module owns talking to the API and nothing about F5's rules.

Never imports from `api/` (`engine/README.md`, "the internals rule": nothing
in `engine/` knows about FastAPI, a locale, or a request).

This does not go through `engine.gemini_client.generate_structured_json`: that
helper refuses to run when `ENGINE_MODE=mock`, but rewrites must work in mock
mode (they always call the real model, exactly as the Anthropic version did).
The API key comes from `GEMINI_API_KEY`, the same key the matcher uses.
"""

from __future__ import annotations

import json
import os
from typing import Any

from engine.gemini_client import get_default_gemini_model, get_gemini_api_key

# Rewrites need some variety: when the validator rejects a first attempt, the
# retry sends the same prompt, and temperature 0 would return the same text.
DEFAULT_TEMPERATURE = 0.4

_client: Any = None


class RateLimitedError(RuntimeError):
    """The model provider answered 429 (free-tier quota or rate limit)."""


def get_model() -> str:
    """`GEMINI_REWRITE_MODEL` if set, otherwise the engine's default Gemini model."""
    return os.getenv("GEMINI_REWRITE_MODEL") or get_default_gemini_model()


def _get_client() -> Any:
    """Lazy singleton: importing this module — and running the deterministic
    half of the validator suite (`tests/test_rewrite_validator.py`) — must not
    require `GEMINI_API_KEY` to be set."""
    global _client
    if _client is None:
        api_key = get_gemini_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        from google import genai

        _client = genai.Client(api_key=api_key)
    return _client


def call_structured(
    *,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    tool_schema: dict[str, Any],
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Call the model and return its answer as a dict shaped by `tool_schema`.

    The caller parses the dict with a Pydantic model and gets Pydantic's own
    error messages for anything the model got wrong, rather than a JSON parse
    error on free text. `tool_name` and `tool_description` are kept so call
    sites need no change; Gemini has no tool-call step, so the description is
    added to the system prompt instead.
    """
    from google.genai import errors, types

    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=f"{system}\n\n{tool_description}".strip(),
        response_mime_type="application/json",
        response_json_schema=tool_schema,
        temperature=DEFAULT_TEMPERATURE if temperature is None else temperature,
        max_output_tokens=max_tokens,
    )
    try:
        response = client.models.generate_content(model=get_model(), contents=user, config=config)
    except errors.APIError as err:
        if getattr(err, "code", None) == 429:
            raise RateLimitedError("The model provider rate-limited this request.") from err
        raise

    candidates = response.candidates or []
    finish = candidates[0].finish_reason if candidates else None
    if finish is not None and getattr(finish, "name", str(finish)) == "MAX_TOKENS":
        # Truncated mid-generation: the JSON may still parse but be cut off
        # partway through, which is worse than an obvious failure because it
        # looks like real data. Fail loudly instead.
        raise RuntimeError(
            f"Model response for {tool_name!r} was truncated (finish_reason=MAX_TOKENS); "
            f"raise max_tokens or shorten the prompt."
        )

    text = response.text
    if not text:
        raise RuntimeError(f"Model returned no content for {tool_name!r}.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Model returned invalid JSON for {tool_name!r}.") from err
    if not isinstance(data, dict):
        raise RuntimeError(f"Model returned {type(data).__name__}, not an object, for {tool_name!r}.")
    return data
