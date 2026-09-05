from __future__ import annotations

from pathlib import Path

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


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_read_document_returns_full_text(tmp_path: Path) -> None:
    path = _write(tmp_path / "statement.txt", _CURRENT_STATEMENT)

    result = read_document(path)

    assert result["document"] == "statement.txt"
    assert "Portfolio Company X" in result["text"]


def test_read_document_missing_path_raises() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        read_document("/nonexistent/statement.txt")


def test_find_section_locates_named_heading(tmp_path: Path) -> None:
    path = _write(tmp_path / "statement.txt", _CURRENT_STATEMENT)

    result = find_section(path, "Subsequent Events")

    assert result["found"] is True
    assert "No subsequent events occurred" in result["text"]
    assert "Portfolio Company Investments" not in result["text"]


def test_find_section_reports_not_found(tmp_path: Path) -> None:
    path = _write(tmp_path / "statement.txt", _CURRENT_STATEMENT)

    result = find_section(path, "Related Party Transactions")

    assert result["found"] is False


def test_find_entity_returns_every_occurrence(tmp_path: Path) -> None:
    path = _write(tmp_path / "statement.txt", _CURRENT_STATEMENT)

    result = find_entity(path, "Portfolio Company X")

    assert result["occurrences"] == 1
    assert "controlled investment" in result["matches"][0]["context"]


def test_compare_periods_reports_added_and_removed_lines(tmp_path: Path) -> None:
    current_path = _write(tmp_path / "current.txt", _CURRENT_STATEMENT)
    prior_path = _write(tmp_path / "prior.txt", _PRIOR_STATEMENT)

    result = compare_periods(current_path, prior_path)

    assert result["identical"] is False
    assert any("No subsequent events" in line for line in result["lines_added"])
    assert any("completed a transaction" in line for line in result["lines_removed"])


def test_compare_periods_identical_documents(tmp_path: Path) -> None:
    current_path = _write(tmp_path / "current.txt", _CURRENT_STATEMENT)
    same_path = _write(tmp_path / "same.txt", _CURRENT_STATEMENT)

    result = compare_periods(current_path, same_path)

    assert result["identical"] is True
    assert result["lines_added"] == []
    assert result["lines_removed"] == []


def test_compare_dates_flags_carried_forward_and_new_dates(tmp_path: Path) -> None:
    current_path = _write(tmp_path / "current.txt", _CURRENT_STATEMENT)
    prior_path = _write(tmp_path / "prior.txt", _PRIOR_STATEMENT)

    result = compare_dates(current_path, prior_path)

    assert "2026-06-30" in result["dates_only_in_current"]
    assert "2026-03-31" in result["dates_only_in_prior"]
    assert "2026-05-17" in result["dates_only_in_prior"]
