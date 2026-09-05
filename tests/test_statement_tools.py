from __future__ import annotations

import pytest

from app.statement_tools import (
    compare_dates,
    compare_periods,
    find_entity,
    find_section,
    read_document,
)

_CURRENT_STATEMENT = """Notes to Financial Statements

Portfolio Company Investments
Portfolio Company X remains a controlled investment as of 2026-06-30.

Subsequent Events
No subsequent events occurred after 2026-06-30.
"""

_PRIOR_STATEMENT = """Notes to Financial Statements

Portfolio Company Investments
Portfolio Company X remains a controlled investment as of 2026-03-31.

Subsequent Events
Portfolio Company X completed a transaction on 2026-05-17.
"""


def test_read_document_returns_full_text() -> None:
    result = read_document(_CURRENT_STATEMENT.encode(), "statement.txt")

    assert result["document"] == "statement.txt"
    assert "Portfolio Company X" in result["text"]


def test_read_document_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError, match="must be PDF, TXT or Markdown"):
        read_document(b"binary content", "statement.docx")


def test_find_section_locates_named_heading() -> None:
    result = find_section(_CURRENT_STATEMENT.encode(), "statement.txt", "Subsequent Events")

    assert result["found"] is True
    assert "No subsequent events occurred" in result["text"]
    assert "Portfolio Company Investments" not in result["text"]


def test_find_section_reports_not_found() -> None:
    result = find_section(
        _CURRENT_STATEMENT.encode(), "statement.txt", "Related Party Transactions"
    )

    assert result["found"] is False


def test_find_entity_returns_every_occurrence() -> None:
    result = find_entity(_CURRENT_STATEMENT.encode(), "statement.txt", "Portfolio Company X")

    assert result["occurrences"] == 1
    assert "controlled investment" in result["matches"][0]["context"]


def test_compare_periods_reports_added_and_removed_lines() -> None:
    result = compare_periods(
        _CURRENT_STATEMENT.encode(), "current.txt", _PRIOR_STATEMENT.encode(), "prior.txt"
    )

    assert result["identical"] is False
    assert any("No subsequent events" in line for line in result["lines_added"])
    assert any("completed a transaction" in line for line in result["lines_removed"])


def test_compare_periods_identical_documents() -> None:
    result = compare_periods(
        _CURRENT_STATEMENT.encode(), "current.txt", _CURRENT_STATEMENT.encode(), "same.txt"
    )

    assert result["identical"] is True
    assert result["lines_added"] == []
    assert result["lines_removed"] == []


def test_compare_dates_flags_carried_forward_and_new_dates() -> None:
    result = compare_dates(
        _CURRENT_STATEMENT.encode(), "current.txt", _PRIOR_STATEMENT.encode(), "prior.txt"
    )

    assert "2026-06-30" in result["dates_only_in_current"]
    assert "2026-03-31" in result["dates_only_in_prior"]
    assert "2026-05-17" in result["dates_only_in_prior"]
