# tests/test_rewrite_llm.py
"""engine/rewrite/llm.py against a fake Gemini client: no network, no key."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from google.genai import errors

from engine.rewrite import llm

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def _client(*, text: str | None = '{"ok": true}', finish: str = "STOP", raises: Exception | None = None):
    captured: dict = {}

    def generate_content(*, model, contents, config):
        captured.update(model=model, contents=contents, config=config)
        if raises:
            raise raises
        cand = SimpleNamespace(finish_reason=SimpleNamespace(name=finish))
        return SimpleNamespace(text=text, candidates=[cand])

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return client, captured


def _call(client, **kw):
    with patch.object(llm, "_get_client", return_value=client):
        return llm.call_structured(
            system="sys", user="usr", tool_name="t", tool_description="desc", tool_schema=SCHEMA, **kw
        )


def test_returns_the_parsed_object_and_sends_schema_prompt_and_model() -> None:
    client, seen = _client()
    assert _call(client) == {"ok": True}
    assert seen["contents"] == "usr"
    assert seen["model"] == llm.get_model()
    assert seen["config"].response_json_schema == SCHEMA
    assert seen["config"].response_mime_type == "application/json"
    assert "sys" in seen["config"].system_instruction and "desc" in seen["config"].system_instruction


def test_uses_a_nonzero_temperature_by_default_so_a_retry_can_differ() -> None:
    client, seen = _client()
    _call(client)
    assert seen["config"].temperature > 0


def test_a_429_becomes_a_rate_limited_error() -> None:
    client, _ = _client(raises=errors.APIError(429, {"error": {"message": "quota"}}))
    with pytest.raises(llm.RateLimitedError):
        _call(client)


def test_other_api_errors_pass_through_unchanged() -> None:
    client, _ = _client(raises=errors.APIError(500, {"error": {"message": "boom"}}))
    with pytest.raises(errors.APIError):
        _call(client)


def test_a_truncated_response_fails_loudly() -> None:
    client, _ = _client(finish="MAX_TOKENS")
    with pytest.raises(RuntimeError, match="truncated"):
        _call(client)


@pytest.mark.parametrize("text", [None, "", "not json", "[1, 2]"])
def test_empty_or_non_object_output_fails(text) -> None:
    client, _ = _client(text=text)
    with pytest.raises(RuntimeError):
        _call(client)


def test_missing_key_raises_before_any_call(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_client", None)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm.call_structured(
            system="s", user="u", tool_name="t", tool_description="d", tool_schema=SCHEMA
        )


def test_rewrite_model_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_REWRITE_MODEL", "gemini-test-model")
    assert llm.get_model() == "gemini-test-model"
