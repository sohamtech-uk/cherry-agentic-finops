from __future__ import annotations

from app.nav_reconciliation import validate_balance_sheet_equity, validate_nav_bridge


def test_balance_sheet_equity_passes_when_it_foots() -> None:
    result = validate_balance_sheet_equity(
        assets="105200000",
        liabilities="12700000",
        reported_equity="92500000",
    )

    assert result["control"] == "BS_EQUITY_RECONCILIATION"
    assert result["status"] == "PASS"
    assert result["severity"] == "pass"
    assert result["expected_equity"] == "92500000.00"
    assert result["difference"] == "0.00"


def test_balance_sheet_equity_fails_and_reports_difference() -> None:
    result = validate_balance_sheet_equity(
        assets="105200000",
        liabilities="12700000",
        reported_equity="89800000",
    )

    assert result["status"] == "FAIL"
    assert result["severity"] == "critical"
    assert result["expected_equity"] == "92500000.00"
    assert result["reported_equity"] == "89800000.00"
    assert result["difference"] == "2700000.00"


def test_balance_sheet_equity_within_tolerance_passes() -> None:
    result = validate_balance_sheet_equity(
        assets="100000000",
        liabilities="0",
        reported_equity="99999999.995",
        tolerance="0.01",
    )

    assert result["status"] == "PASS"


def test_nav_bridge_passes_when_it_foots() -> None:
    result = validate_nav_bridge(
        opening_nav="91000000",
        contributions="500000",
        investment_movement="200000",
        fx_movement="-25000",
        income="150000",
        expenses="75000",
        distributions="325000",
        reported_closing_nav="91425000",
    )

    assert result["control"] == "NAV_BRIDGE"
    assert result["status"] == "PASS"
    assert result["difference"] == "0.00"


def test_nav_bridge_fails_and_reports_difference() -> None:
    result = validate_nav_bridge(
        opening_nav="91000000",
        contributions="500000",
        investment_movement="200000",
        fx_movement="-25000",
        income="150000",
        expenses="75000",
        distributions="325000",
        reported_closing_nav="91625220",
    )

    assert result["status"] == "FAIL"
    assert result["severity"] == "critical"
    assert result["expected_closing_nav"] == "91425000.00"
    assert result["difference"] == "-200220.00"
