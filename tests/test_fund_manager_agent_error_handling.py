from __future__ import annotations

from typing import Any

import pytest
from google.adk.runners import Runner

from app.fund_manager_agentic import run_agentic_analysis
from app.fund_manager_stages import plan_case_controls


async def _boom_run_async(self: Runner, **kwargs: Any):
    """A fake `Runner.run_async` standing in for a Gemini/ADK call that fails outright.

    Network/auth/quota failures from the real google-genai client surface as arbitrary exception
    types, not RuntimeError -- this simulates that with a plain ConnectionError."""

    raise ConnectionError("Gemini API unreachable")
    yield  # pragma: no cover - unreachable; keeps this an async generator function


@pytest.mark.asyncio
async def test_plan_case_controls_wraps_unexpected_agent_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Runner, "run_async", _boom_run_async)

    with pytest.raises(RuntimeError, match="could not complete"):
        await plan_case_controls({"sources": []})


@pytest.mark.asyncio
async def test_run_agentic_analysis_wraps_unexpected_agent_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Runner, "run_async", _boom_run_async)

    with pytest.raises(RuntimeError, match="could not complete"):
        await run_agentic_analysis([("positions.json", b"[]", None)])
