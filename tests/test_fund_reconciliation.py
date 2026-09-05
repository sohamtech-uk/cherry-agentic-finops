from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.fund_reconciliation import (
    CashBalance,
    ExceptionItem,
    ExposureLimit,
    Position,
    PriceRecord,
    Trade,
    detect_exposure_breaches,
    detect_stale_prices,
    detect_unsettled_trades,
    parse_cash_balances,
    parse_exposure_limits,
    parse_positions,
    parse_prices,
    parse_trades,
    prioritise_exceptions,
    reconcile_cash,
    reconcile_positions,
    reconcile_trades,
)

# --- parsing --------------------------------------------------------------------------------


def test_parse_positions_accepts_bare_array() -> None:
    payload = [{"fund": "Fund X", "security_id": "SEC1", "quantity": 100, "price": 10}]
    positions = parse_positions(json.dumps(payload).encode())
    assert positions == [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]


def test_parse_positions_accepts_object_shape() -> None:
    payload = {
        "positions": [{"fund": "Fund X", "security_id": "SEC1", "quantity": 100, "price": 10}]
    }
    positions = parse_positions(json.dumps(payload).encode())
    assert len(positions) == 1


def test_parse_positions_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_positions(b"")


def test_parse_positions_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="Expected a JSON array"):
        parse_positions(json.dumps({"not_positions": []}).encode())


def test_parse_cash_balances_round_trips() -> None:
    payload = {
        "cash_balances": [{"fund": "Fund X", "account": "ACC1", "currency": "usd", "balance": 100}]
    }
    balances = parse_cash_balances(json.dumps(payload).encode())
    assert balances[0].currency == "USD"


def test_parse_trades_round_trips() -> None:
    payload = [
        {
            "trade_id": "T1",
            "fund": "Fund X",
            "security_id": "SEC1",
            "side": "BUY",
            "quantity": 100,
            "price": 10,
            "trade_date": "2026-06-01",
        }
    ]
    trades = parse_trades(json.dumps(payload).encode())
    assert trades[0].side == "buy"
    assert trades[0].status == "unsettled"


def test_parse_prices_and_exposure_limits_round_trip() -> None:
    prices = parse_prices(
        json.dumps([{"security_id": "SEC1", "price": 10, "price_date": "2026-06-01"}]).encode()
    )
    assert prices[0].price == Decimal("10.00")
    limits = parse_exposure_limits(
        json.dumps(
            {"limits": [{"label": "L1", "scope": "gross_exposure", "max_percent_of_nav": 100}]}
        ).encode()
    )
    assert limits[0].max_percent_of_nav == Decimal("100")


# --- reconcile_positions ---------------------------------------------------------------------


def test_reconcile_positions_matches_clean_positions() -> None:
    internal = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]
    external = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]

    result = reconcile_positions(internal, external)

    assert result.matched_count == 1
    assert result.breaks == []


def test_reconcile_positions_flags_missing_internal() -> None:
    internal: list[Position] = []
    external = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]

    result = reconcile_positions(internal, external)

    assert len(result.breaks) == 1
    assert result.breaks[0].break_type == "missing_internal"
    assert result.breaks[0].difference == Decimal("1000.00")


def test_reconcile_positions_flags_missing_external() -> None:
    internal = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]
    external: list[Position] = []

    result = reconcile_positions(internal, external)

    assert result.breaks[0].break_type == "missing_external"


def test_reconcile_positions_flags_quantity_mismatch() -> None:
    internal = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]
    external = [Position(fund="Fund X", security_id="SEC1", quantity=90, price=10)]

    result = reconcile_positions(internal, external)

    assert result.breaks[0].break_type == "quantity_mismatch"
    assert result.breaks[0].difference == Decimal("10.00")


def test_reconcile_positions_flags_market_value_mismatch_when_quantity_matches() -> None:
    internal = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]
    external = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=11)]

    result = reconcile_positions(internal, external)

    assert result.breaks[0].break_type == "market_value_mismatch"
    assert result.breaks[0].difference == Decimal("-100.00")


def test_reconcile_positions_uses_explicit_market_value_when_supplied() -> None:
    internal = [
        Position(fund="Fund X", security_id="SEC1", quantity=100, price=10, market_value=999)
    ]
    external = [
        Position(fund="Fund X", security_id="SEC1", quantity=100, price=10, market_value=999)
    ]

    result = reconcile_positions(internal, external)

    assert result.matched_count == 1


def test_reconcile_positions_to_exceptions_carries_impact_amount() -> None:
    internal = [Position(fund="Fund X", security_id="SEC1", quantity=100, price=10)]
    external = [Position(fund="Fund X", security_id="SEC1", quantity=90, price=10)]
    result = reconcile_positions(internal, external)

    exceptions = result.to_exceptions()

    assert len(exceptions) == 1
    assert exceptions[0].category == "position"
    assert exceptions[0].key == "SEC1"
    assert exceptions[0].impact_amount == Decimal("10.00")


# --- reconcile_cash ---------------------------------------------------------------------------


def test_reconcile_cash_matches_and_flags_mismatch() -> None:
    internal = [
        CashBalance(fund="Fund X", account="ACC1", currency="USD", balance=1000),
        CashBalance(fund="Fund X", account="ACC2", currency="USD", balance=500),
    ]
    external = [
        CashBalance(fund="Fund X", account="ACC1", currency="USD", balance=1000),
        CashBalance(fund="Fund X", account="ACC2", currency="USD", balance=450),
    ]

    result = reconcile_cash(internal, external)

    assert result.matched_count == 1
    assert len(result.breaks) == 1
    assert result.breaks[0].break_type == "balance_mismatch"
    assert result.breaks[0].account == "ACC2"
    assert result.breaks[0].difference == Decimal("50.00")


def test_reconcile_cash_treats_different_currencies_as_different_accounts() -> None:
    internal = [CashBalance(fund="Fund X", account="ACC1", currency="USD", balance=1000)]
    external = [CashBalance(fund="Fund X", account="ACC1", currency="EUR", balance=1000)]

    result = reconcile_cash(internal, external)

    assert len(result.breaks) == 2
    assert {b.break_type for b in result.breaks} == {"missing_internal", "missing_external"}


# --- reconcile_trades -------------------------------------------------------------------------


def _trade(**overrides: object) -> Trade:
    payload: dict[str, object] = {
        "trade_id": "T1",
        "fund": "Fund X",
        "security_id": "SEC1",
        "side": "buy",
        "quantity": 100,
        "price": 10,
        "trade_date": date(2026, 6, 1),
    }
    payload.update(overrides)
    return Trade.model_validate(payload)


def test_reconcile_trades_matches_clean_trade() -> None:
    result = reconcile_trades([_trade()], [_trade()])
    assert result.matched_count == 1
    assert result.breaks == []


def test_reconcile_trades_flags_side_mismatch() -> None:
    result = reconcile_trades([_trade(side="buy")], [_trade(side="sell")])
    assert result.breaks[0].break_type == "side_mismatch"


def test_reconcile_trades_flags_quantity_mismatch() -> None:
    result = reconcile_trades([_trade(quantity=100)], [_trade(quantity=90)])
    assert result.breaks[0].break_type == "quantity_mismatch"


def test_reconcile_trades_flags_price_mismatch() -> None:
    result = reconcile_trades([_trade(price=10)], [_trade(price=11)])
    assert result.breaks[0].break_type == "price_mismatch"


def test_reconcile_trades_flags_missing_trade() -> None:
    result = reconcile_trades([], [_trade()])
    assert result.breaks[0].break_type == "missing_internal"


def test_reconcile_trades_to_exceptions_computes_impact_from_quantity_times_price() -> None:
    result = reconcile_trades([_trade(quantity=100, price=10)], [])
    exceptions = result.to_exceptions()
    assert exceptions[0].impact_amount == Decimal("1000.00")


# --- detect_stale_prices ----------------------------------------------------------------------


def test_detect_stale_prices_ignores_fresh_prices() -> None:
    prices = [PriceRecord(security_id="SEC1", price=10, price_date=date(2026, 6, 28))]
    findings = detect_stale_prices(prices, as_of=date(2026, 6, 30), max_age_days=3)
    assert findings == []


def test_detect_stale_prices_flags_warning_then_high() -> None:
    prices = [
        PriceRecord(security_id="WARN", price=10, price_date=date(2026, 6, 25)),  # 5 days old
        PriceRecord(security_id="HIGH", price=10, price_date=date(2026, 5, 1)),  # 60 days old
    ]
    findings = detect_stale_prices(prices, as_of=date(2026, 6, 30), max_age_days=3)

    by_id = {f.security_id: f for f in findings}
    assert by_id["WARN"].severity == "warning"
    assert by_id["HIGH"].severity == "high"
    # sorted oldest-first
    assert findings[0].security_id == "HIGH"


# --- detect_unsettled_trades ------------------------------------------------------------------


def test_detect_unsettled_trades_ignores_settled_and_not_yet_due() -> None:
    trades = [
        _trade(trade_id="T1", status="settled", settlement_date=date(2026, 6, 1)),
        _trade(trade_id="T2", status="unsettled", settlement_date=date(2026, 7, 5)),
        _trade(trade_id="T3", status="unsettled", settlement_date=None),
    ]
    findings = detect_unsettled_trades(trades, as_of=date(2026, 6, 30))
    assert findings == []


def test_detect_unsettled_trades_escalates_past_grace_period() -> None:
    trades = [
        _trade(trade_id="WARN", status="unsettled", settlement_date=date(2026, 6, 28)),  # 2 days
        _trade(trade_id="HIGH", status="unsettled", settlement_date=date(2026, 6, 1)),  # 29 days
    ]
    findings = detect_unsettled_trades(trades, as_of=date(2026, 6, 30), grace_days=3)

    by_id = {f.trade_id: f for f in findings}
    assert by_id["WARN"].severity == "warning"
    assert by_id["HIGH"].severity == "high"
    assert findings[0].trade_id == "HIGH"


# --- detect_exposure_breaches -----------------------------------------------------------------


def test_detect_exposure_breaches_requires_nonzero_nav() -> None:
    with pytest.raises(ValueError, match="non-zero"):
        detect_exposure_breaches([], nav=Decimal("0"), limits=[])


def test_detect_exposure_breaches_single_position() -> None:
    positions = [Position(fund="Fund X", security_id="SEC1", quantity=1, price=15)]
    limits = [
        ExposureLimit(label="Single position cap", scope="single_position", max_percent_of_nav=10)
    ]

    breaches = detect_exposure_breaches(positions, nav=Decimal("100"), limits=limits)

    assert len(breaches) == 1
    assert breaches[0].key == "SEC1"
    assert breaches[0].exposure_percent == Decimal("15.00")


def test_detect_exposure_breaches_gross_exposure() -> None:
    positions = [
        Position(fund="Fund X", security_id="SEC1", quantity=1, price=60),
        Position(fund="Fund X", security_id="SEC2", quantity=1, price=50),
    ]
    limits = [ExposureLimit(label="Gross cap", scope="gross_exposure", max_percent_of_nav=100)]

    breaches = detect_exposure_breaches(positions, nav=Decimal("100"), limits=limits)

    assert len(breaches) == 1
    assert breaches[0].exposure_percent == Decimal("110.00")


def test_detect_exposure_breaches_issuer_targeted_limit() -> None:
    positions = [
        Position(fund="Fund X", security_id="SEC1", quantity=1, price=20, issuer="Acme"),
        Position(fund="Fund X", security_id="SEC2", quantity=1, price=5, issuer="Acme"),
        Position(fund="Fund X", security_id="SEC3", quantity=1, price=5, issuer="Globex"),
    ]
    limits = [ExposureLimit(label="Acme cap", scope="issuer", key="Acme", max_percent_of_nav=10)]

    breaches = detect_exposure_breaches(positions, nav=Decimal("100"), limits=limits)

    assert len(breaches) == 1
    assert breaches[0].key == "Acme"
    assert breaches[0].exposure_percent == Decimal("25.00")


def test_detect_exposure_breaches_untargeted_issuer_limit_checks_every_issuer() -> None:
    positions = [
        Position(fund="Fund X", security_id="SEC1", quantity=1, price=20, issuer="Acme"),
        Position(fund="Fund X", security_id="SEC2", quantity=1, price=5, issuer="Globex"),
    ]
    limits = [
        ExposureLimit(label="No single issuer", scope="issuer", key=None, max_percent_of_nav=10)
    ]

    breaches = detect_exposure_breaches(positions, nav=Decimal("100"), limits=limits)

    assert len(breaches) == 1
    assert breaches[0].key == "Acme"


def test_detect_exposure_breaches_sector_scope() -> None:
    positions = [Position(fund="Fund X", security_id="SEC1", quantity=1, price=20, sector="Tech")]
    limits = [ExposureLimit(label="Tech cap", scope="sector", key="Tech", max_percent_of_nav=10)]

    breaches = detect_exposure_breaches(positions, nav=Decimal("100"), limits=limits)

    assert len(breaches) == 1
    assert breaches[0].scope == "sector"


def test_detect_exposure_breaches_returns_nothing_when_within_limit() -> None:
    positions = [Position(fund="Fund X", security_id="SEC1", quantity=1, price=5)]
    limits = [
        ExposureLimit(label="Single position cap", scope="single_position", max_percent_of_nav=10)
    ]

    breaches = detect_exposure_breaches(positions, nav=Decimal("100"), limits=limits)

    assert breaches == []


# --- prioritise_exceptions --------------------------------------------------------------------


def test_prioritise_exceptions_ranks_severity_then_impact() -> None:
    items = [
        ExceptionItem(
            category="cash",
            code="c1",
            title="low high",
            detail="",
            severity="high",
            impact_amount=10,
        ),
        ExceptionItem(
            category="cash",
            code="c2",
            title="warn",
            detail="",
            severity="warning",
            impact_amount=1_000_000,
        ),
        ExceptionItem(
            category="cash",
            code="c3",
            title="big high",
            detail="",
            severity="high",
            impact_amount=1_000,
        ),
    ]

    ranked = prioritise_exceptions(items)

    assert [item.code for item in ranked] == ["c3", "c1", "c2"]


def test_prioritise_exceptions_respects_top_n() -> None:
    items = [
        ExceptionItem(
            category="cash", code=f"c{i}", title="x", detail="", severity="high", impact_amount=i
        )
        for i in range(5)
    ]
    ranked = prioritise_exceptions(items, top_n=2)
    assert len(ranked) == 2
    assert ranked[0].code == "c4"
