"""Deterministic NAV Guardian reconciliation controls.

These are pure accounting checks with no LLM involvement, matching the "LLM for
interpretation; deterministic code for accounting" boundary used across Cherry Agent. Every
control returns PASS/FAIL plus the figures used, so an agent can explain the result without
recomputing it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

TWOPLACES = Decimal("0.01")
DEFAULT_TOLERANCE = "0.01"


def money(value: Decimal | float | int | str | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def validate_balance_sheet_equity(
    assets: Decimal | float | int | str,
    liabilities: Decimal | float | int | str,
    reported_equity: Decimal | float | int | str,
    tolerance: Decimal | float | int | str = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """NAV Guardian Check #1: assets minus liabilities must foot to reported equity.

    Args:
        assets: Total balance-sheet assets.
        liabilities: Total balance-sheet liabilities.
        reported_equity: Reported partners' capital / equity balance.
        tolerance: Maximum absolute difference still treated as a rounding pass.
    """

    assets_amount = money(assets)
    liabilities_amount = money(liabilities)
    reported_amount = money(reported_equity)
    tolerance_amount = money(tolerance)
    expected_amount = money(assets_amount - liabilities_amount)
    difference = money(expected_amount - reported_amount)
    passed = abs(difference) <= tolerance_amount

    return {
        "control": "BS_EQUITY_RECONCILIATION",
        "status": "PASS" if passed else "FAIL",
        "severity": "pass" if passed else "critical",
        "assets": str(assets_amount),
        "liabilities": str(liabilities_amount),
        "expected_equity": str(expected_amount),
        "reported_equity": str(reported_amount),
        "difference": str(difference),
    }


def validate_nav_bridge(
    opening_nav: Decimal | float | int | str,
    contributions: Decimal | float | int | str,
    investment_movement: Decimal | float | int | str,
    fx_movement: Decimal | float | int | str,
    income: Decimal | float | int | str,
    expenses: Decimal | float | int | str,
    distributions: Decimal | float | int | str,
    reported_closing_nav: Decimal | float | int | str,
    tolerance: Decimal | float | int | str = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """NAV Guardian Check #2: independently recompute the NAV bridge and compare to the
    administrator's reported closing NAV.

    Closing NAV = Opening NAV + contributions +/- investment movement +/- FX + income -
    expenses - distributions. Callers pass investment_movement and fx_movement already signed
    (negative for a loss/outflow).

    Args:
        opening_nav: Prior-period closing NAV.
        contributions: Capital contributions received in the period.
        investment_movement: Signed change in investment valuations.
        fx_movement: Signed foreign-exchange movement.
        income: Income earned in the period.
        expenses: Expenses incurred in the period.
        distributions: Distributions paid in the period.
        reported_closing_nav: The administrator's reported closing NAV.
        tolerance: Maximum absolute difference still treated as a rounding pass.
    """

    opening_amount = money(opening_nav)
    contributions_amount = money(contributions)
    investment_amount = money(investment_movement)
    fx_amount = money(fx_movement)
    income_amount = money(income)
    expenses_amount = money(expenses)
    distributions_amount = money(distributions)
    reported_amount = money(reported_closing_nav)
    tolerance_amount = money(tolerance)

    expected_amount = money(
        opening_amount
        + contributions_amount
        + investment_amount
        + fx_amount
        + income_amount
        - expenses_amount
        - distributions_amount
    )
    difference = money(expected_amount - reported_amount)
    passed = abs(difference) <= tolerance_amount

    return {
        "control": "NAV_BRIDGE",
        "status": "PASS" if passed else "FAIL",
        "severity": "pass" if passed else "critical",
        "opening_nav": str(opening_amount),
        "contributions": str(contributions_amount),
        "investment_movement": str(investment_amount),
        "fx_movement": str(fx_amount),
        "income": str(income_amount),
        "expenses": str(expenses_amount),
        "distributions": str(distributions_amount),
        "expected_closing_nav": str(expected_amount),
        "reported_closing_nav": str(reported_amount),
        "difference": str(difference),
    }
