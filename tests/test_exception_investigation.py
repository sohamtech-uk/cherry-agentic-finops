from __future__ import annotations

from decimal import Decimal

import pytest

from app.exception_investigation import investigate_exception
from app.fund_reconciliation import ExceptionItem


def _item(
    category: str,
    code: str,
    *,
    key: str | None,
    severity: str,
    impact_amount: int | str = 0,
    title: str = "title",
    detail: str = "detail",
) -> ExceptionItem:
    return ExceptionItem(
        category=category,
        code=code,
        key=key,
        title=title,
        detail=detail,
        severity=severity,
        impact_amount=impact_amount,
    )


def test_investigate_exception_raises_on_empty_list() -> None:
    with pytest.raises(ValueError, match="No exceptions supplied"):
        investigate_exception([])


def test_investigate_exception_raises_when_code_not_found() -> None:
    items = [_item("cash", "cash.balance_mismatch", key="ACC1", severity="high")]
    with pytest.raises(ValueError, match="No exception with code"):
        investigate_exception(items, code="does.not.exist")


def test_investigate_exception_raises_when_key_not_found() -> None:
    items = [_item("cash", "cash.balance_mismatch", key="ACC1", severity="high")]
    with pytest.raises(ValueError, match="No exception with key"):
        investigate_exception(items, key="does-not-exist")


def test_investigate_exception_defaults_to_highest_priority_and_finds_related() -> None:
    cash_break = _item(
        "cash",
        "cash.balance_mismatch",
        key="ACC1",
        severity="high",
        impact_amount=500,
        detail="Internal 1000 vs external 500.",
    )
    trade_break = _item(
        "trade", "trade.price_mismatch", key="ACC1", severity="high", impact_amount=100
    )
    unrelated = _item(
        "position", "position.quantity_mismatch", key="SEC9", severity="warning", impact_amount=50
    )

    result = investigate_exception([trade_break, unrelated, cash_break])

    assert result.exception.code == "cash.balance_mismatch"
    assert [item.code for item in result.related_exceptions] == ["trade.price_mismatch"]
    assert "1 other exception(s) share key 'ACC1'" in result.likely_root_cause
    assert "trade" in result.likely_root_cause
    assert result.recommended_owner == "Treasury / fund controller"
    assert "bank statement transaction" in result.recommended_action
    assert result.next_step == "escalate_immediately"
    assert "multiple records" in result.rationale


def test_investigate_exception_selects_by_code_overriding_priority() -> None:
    cash_break = _item(
        "cash", "cash.balance_mismatch", key="ACC1", severity="high", impact_amount=500
    )
    trade_break = _item(
        "trade", "trade.price_mismatch", key="ACC1", severity="high", impact_amount=100
    )
    isolated = _item(
        "position", "position.quantity_mismatch", key="SEC9", severity="warning", impact_amount=50
    )

    result = investigate_exception(
        [cash_break, trade_break, isolated], code="position.quantity_mismatch"
    )

    assert result.exception.code == "position.quantity_mismatch"
    assert result.related_exceptions == []
    assert result.next_step == "request_evidence"
    assert "not yet confirmed" in result.rationale


def test_investigate_exception_selects_by_key() -> None:
    cash_break = _item(
        "cash", "cash.balance_mismatch", key="ACC1", severity="high", impact_amount=500
    )
    trade_break = _item(
        "trade", "trade.price_mismatch", key="ACC1", severity="high", impact_amount=100
    )

    result = investigate_exception([trade_break, cash_break], key="ACC1")

    assert result.exception.code == "cash.balance_mismatch"


def test_investigate_exception_assign_and_monitor_for_isolated_high_severity() -> None:
    stale_price = _item(
        "stale_price", "stale_price.overdue", key="SEC5", severity="high", impact_amount=200
    )

    result = investigate_exception([stale_price])

    assert result.related_exceptions == []
    assert result.next_step == "assign_and_monitor"
    assert result.recommended_owner == "Valuation team"
    assert "current price" in result.recommended_action
    assert "isolated to this key" in result.rationale


def test_investigate_exception_accept_and_close_for_non_warning_non_high_severity() -> None:
    info_item = _item(
        "expense_allocation", "expense_allocation.amount_mismatch", key="EXP1", severity="info"
    )

    result = investigate_exception([info_item])

    assert result.next_step == "accept_and_close"
    assert result.recommended_owner == "Fund controller"


def test_investigate_exception_impact_amount_is_decimal() -> None:
    item = _item(
        "cash", "cash.balance_mismatch", key="ACC1", severity="high", impact_amount="500.00"
    )

    result = investigate_exception([item])

    assert result.exception.impact_amount == Decimal("500.00")
