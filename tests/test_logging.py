"""Tests for library logging: silent by default, routed through stdlib, never leaks credentials."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from httpx import Response

from calm_client import CalmClient
from calm_client.logging import REDACTED, redact_sensitive


def test_redacts_headers_and_body_fields() -> None:
    event = {
        "event": "http_request",
        "headers": {"Cookie": "calm-user-token=secret", "x-session-token": "s", "x-calm-platform": "web"},
        "body": {"username": "me@example.com", "password": "pw", "nested": {"refresh_token": "r"}},
    }
    assert redact_sensitive(None, "debug", event) == {
        "event": "http_request",
        "headers": {"Cookie": REDACTED, "x-session-token": REDACTED, "x-calm-platform": "web"},
        "body": {"username": "me@example.com", "password": REDACTED, "nested": {"refresh_token": REDACTED}},
    }


def test_redacts_raw_json_bodies_with_tokens() -> None:
    event = {"event": "http_response", "body": '{"token": "abc", "user": {}}'}
    assert redact_sensitive(None, "debug", event)["body"] == REDACTED
    harmless = {"event": "http_response", "body": '{"feed": {"id": "sleep"}}'}
    assert redact_sensitive(None, "debug", harmless)["body"] == '{"feed": {"id": "sleep"}}'


@pytest.mark.asyncio
async def test_library_logs_via_stdlib_without_secrets(
    respx_mock: Any, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(return_value=Response(403, json={"error": "denied"}))
    caplog.set_level(logging.DEBUG, logger="calm_client")

    async with CalmClient("secret-token") as client:
        with pytest.raises(Exception, match="login failed"):
            await client.login("me@example.com", "hunter2")

    records = [r for r in caplog.records if r.name == "calm_client"]
    assert records, "expected calm_client log records through the stdlib logger"
    text = "\n".join(r.getMessage() for r in records)
    assert "hunter2" not in text
    assert "secret-token" not in text
    # nothing is printed by the library itself
    assert capsys.readouterr().out == ""


@pytest.fixture
def restore_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Run in a temp dir (configure_logging writes app.log there) and undo global logging config."""
    import structlog

    monkeypatch.chdir(tmp_path)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield tmp_path
    for handler in root.handlers:
        handler.close()
    root.handlers, root.level = handlers, level
    structlog.reset_defaults()


def test_redacts_lists_of_payloads() -> None:
    event = {"event": "x", "body": [{"password": "pw"}, {"ok": 1}]}
    assert redact_sensitive(None, "debug", event)["body"] == [{"password": REDACTED}, {"ok": 1}]


def test_configure_logging_writes_redacted_json_log(restore_logging: Any) -> None:
    from calm_client.logging import configure_logging, logger

    configure_logging(level=logging.INFO)
    logger.info("http_request", headers={"Cookie": "calm-user-token=secret"}, body={"password": "pw"})
    for handler in logging.getLogger().handlers:
        handler.flush()

    log_text = (restore_logging / "app.log").read_text()
    assert "http_request" in log_text
    assert "secret" not in log_text
    assert '"pw"' not in log_text
