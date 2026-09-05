"""Fund-operations reconciliation: positions, cash, trades, stale prices, unsettled trades and
exposure limits.

Extends the NAV Guardian deterministic-control family (app.nav_quality, app.nav_reconciliation)
down one level, from the NAV summary itself to the position/cash/trade records a NAV is built
from. Same architecture throughout this codebase: parsing accepts flexible JSON (an array, or an
object with a named array — matching app.private_markets_io.parse_cash_json's convention);
matching and arithmetic are plain Decimal comparisons, never an LLM; every finding carries the
figures used so a reviewer (or an agent explaining the result) never has to trust an unexplained
verdict.

``prioritise_exceptions`` is the one function here that is domain-agnostic: it accepts
``ExceptionItem`` records from any of the other six checks (each result type has a
``to_exceptions()`` method) and ranks them by severity then materiality, the same ordering
``app.nav_exceptions.group_exceptions_by_root_cause`` uses for NAV-level findings.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.private_markets import FindingSeverity, money

DEFAULT_QUANTITY_TOLERANCE = Decimal("0.0001")
DEFAULT_PRICE_TOLERANCE = Decimal("0.01")
DEFAULT_MONEY_TOLERANCE = Decimal("0.01")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _rows(payload: Any, *names: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows: Any = payload
    elif isinstance(payload, dict):
        rows = None
        for name in names:
            if name in payload:
                rows = payload[name]
                break
    else:
        rows = None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(
            f"Expected a JSON array or an object containing one of {list(names)} as an array "
            "of objects."
        )
    return rows


def _load_json(content: bytes, *names: str) -> list[dict[str, Any]]:
    if not content:
        raise ValueError("Input is empty.")
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Input must be valid UTF-8 JSON.") from exc
    return _rows(payload, *names)


class ExceptionItem(BaseModel):
    """A single triageable finding from any fund-reconciliation check, in a common shape so
    ``prioritise_exceptions`` can rank findings from different checks together."""

    category: Literal[
        "position", "cash", "trade", "stale_price", "unsettled_trade", "exposure_breach"
    ]
    code: str
    key: str | None = None
    title: str
    detail: str
    severity: FindingSeverity
    impact_amount: Decimal = Decimal("0")


# --- Positions -------------------------------------------------------------------------------


class Position(BaseModel):
    fund: str
    security_id: str
    security_name: str | None = None
    quantity: Decimal
    price: Decimal
    market_value: Decimal | None = None
    currency: str = "USD"
    issuer: str | None = None
    sector: str | None = None
    as_of: date | None = None

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def _normalise_required_money(cls, value: Any) -> Decimal:
        return money(value)

    @field_validator("market_value", mode="before")
    @classmethod
    def _normalise_optional_money(cls, value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        return money(value)

    @property
    def resolved_market_value(self) -> Decimal:
        return (
            self.market_value
            if self.market_value is not None
            else money(self.quantity * self.price)
        )


class PositionBreak(BaseModel):
    security_id: str
    security_name: str | None = None
    break_type: Literal[
        "missing_internal", "missing_external", "quantity_mismatch", "market_value_mismatch"
    ]
    internal_quantity: Decimal | None = None
    external_quantity: Decimal | None = None
    internal_market_value: Decimal | None = None
    external_market_value: Decimal | None = None
    difference: Decimal
    severity: FindingSeverity


class PositionReconciliationResult(BaseModel):
    breaks: list[PositionBreak] = Field(default_factory=list)
    matched_count: int = 0
    internal_count: int = 0
    external_count: int = 0

    def to_exceptions(self) -> list[ExceptionItem]:
        return [
            ExceptionItem(
                category="position",
                code=f"position.{item.break_type}",
                key=item.security_id,
                title=f"{item.security_name or item.security_id}: {item.break_type.replace('_', ' ')}",
                detail=(
                    f"Internal {item.internal_quantity if item.internal_quantity is not None else '-'} "
                    f"@ {item.internal_market_value if item.internal_market_value is not None else '-'} "
                    f"vs external {item.external_quantity if item.external_quantity is not None else '-'} "
                    f"@ {item.external_market_value if item.external_market_value is not None else '-'}."
                ),
                severity=item.severity,
                impact_amount=abs(item.difference),
            )
            for item in self.breaks
        ]


def parse_positions(content: bytes) -> list[Position]:
    """Parse a flexible JSON position export: a top-level array, or an object with a
    ``positions`` array."""

    return [Position.model_validate(row) for row in _load_json(content, "positions")]


def reconcile_positions(
    internal: list[Position],
    external: list[Position],
    *,
    quantity_tolerance: Decimal = DEFAULT_QUANTITY_TOLERANCE,
    market_value_tolerance: Decimal = DEFAULT_MONEY_TOLERANCE,
) -> PositionReconciliationResult:
    """Compare an internal position record against an external one (administrator/custodian),
    matched by security_id. Flags missing positions on either side, quantity breaks and market
    value breaks; a quantity match with a market value break usually means a price break."""

    internal_by_id = {position.security_id: position for position in internal}
    external_by_id = {position.security_id: position for position in external}
    breaks: list[PositionBreak] = []
    matched = 0

    for security_id in sorted(set(internal_by_id) | set(external_by_id)):
        internal_position = internal_by_id.get(security_id)
        external_position = external_by_id.get(security_id)
        if internal_position is None:
            breaks.append(
                PositionBreak(
                    security_id=security_id,
                    security_name=external_position.security_name if external_position else None,
                    break_type="missing_internal",
                    external_quantity=external_position.quantity if external_position else None,
                    external_market_value=(
                        external_position.resolved_market_value if external_position else None
                    ),
                    difference=external_position.resolved_market_value
                    if external_position
                    else Decimal("0"),
                    severity=FindingSeverity.HIGH,
                )
            )
            continue
        if external_position is None:
            breaks.append(
                PositionBreak(
                    security_id=security_id,
                    security_name=internal_position.security_name,
                    break_type="missing_external",
                    internal_quantity=internal_position.quantity,
                    internal_market_value=internal_position.resolved_market_value,
                    difference=internal_position.resolved_market_value,
                    severity=FindingSeverity.HIGH,
                )
            )
            continue

        quantity_difference = money(internal_position.quantity - external_position.quantity)
        market_value_difference = money(
            internal_position.resolved_market_value - external_position.resolved_market_value
        )
        security_name = internal_position.security_name or external_position.security_name
        if abs(quantity_difference) > quantity_tolerance:
            breaks.append(
                PositionBreak(
                    security_id=security_id,
                    security_name=security_name,
                    break_type="quantity_mismatch",
                    internal_quantity=internal_position.quantity,
                    external_quantity=external_position.quantity,
                    internal_market_value=internal_position.resolved_market_value,
                    external_market_value=external_position.resolved_market_value,
                    difference=quantity_difference,
                    severity=FindingSeverity.HIGH,
                )
            )
        elif abs(market_value_difference) > market_value_tolerance:
            breaks.append(
                PositionBreak(
                    security_id=security_id,
                    security_name=security_name,
                    break_type="market_value_mismatch",
                    internal_quantity=internal_position.quantity,
                    external_quantity=external_position.quantity,
                    internal_market_value=internal_position.resolved_market_value,
                    external_market_value=external_position.resolved_market_value,
                    difference=market_value_difference,
                    severity=FindingSeverity.HIGH,
                )
            )
        else:
            matched += 1

    return PositionReconciliationResult(
        breaks=breaks,
        matched_count=matched,
        internal_count=len(internal),
        external_count=len(external),
    )


# --- Cash --------------------------------------------------------------------------------------


class CashBalance(BaseModel):
    fund: str
    account: str
    currency: str = "USD"
    balance: Decimal
    as_of: date | None = None

    @field_validator("balance", mode="before")
    @classmethod
    def _normalise_balance(cls, value: Any) -> Decimal:
        return money(value)

    @field_validator("currency")
    @classmethod
    def _normalise_currency(cls, value: str) -> str:
        return value.upper().strip() or "USD"

    @property
    def key(self) -> tuple[str, str]:
        return (self.account, self.currency)


class CashBreak(BaseModel):
    account: str
    currency: str
    break_type: Literal["missing_internal", "missing_external", "balance_mismatch"]
    internal_balance: Decimal | None = None
    external_balance: Decimal | None = None
    difference: Decimal
    severity: FindingSeverity


class CashReconciliationResult(BaseModel):
    breaks: list[CashBreak] = Field(default_factory=list)
    matched_count: int = 0
    internal_count: int = 0
    external_count: int = 0

    def to_exceptions(self) -> list[ExceptionItem]:
        return [
            ExceptionItem(
                category="cash",
                code=f"cash.{item.break_type}",
                key=f"{item.account}/{item.currency}",
                title=f"{item.account} ({item.currency}): {item.break_type.replace('_', ' ')}",
                detail=(
                    f"Internal {item.internal_balance if item.internal_balance is not None else '-'} "
                    f"vs external {item.external_balance if item.external_balance is not None else '-'}."
                ),
                severity=item.severity,
                impact_amount=abs(item.difference),
            )
            for item in self.breaks
        ]


def parse_cash_balances(content: bytes) -> list[CashBalance]:
    """Parse a flexible JSON cash-balance export: a top-level array, or an object with a
    ``cash_balances`` array."""

    return [CashBalance.model_validate(row) for row in _load_json(content, "cash_balances")]


def reconcile_cash(
    internal: list[CashBalance],
    external: list[CashBalance],
    *,
    tolerance: Decimal = DEFAULT_MONEY_TOLERANCE,
) -> CashReconciliationResult:
    """Compare internal cash balances against an external source (bank/custodian statement),
    matched by (account, currency)."""

    internal_by_key = {balance.key: balance for balance in internal}
    external_by_key = {balance.key: balance for balance in external}
    breaks: list[CashBreak] = []
    matched = 0

    for key in sorted(set(internal_by_key) | set(external_by_key)):
        account, currency = key
        internal_balance = internal_by_key.get(key)
        external_balance = external_by_key.get(key)
        if internal_balance is None:
            breaks.append(
                CashBreak(
                    account=account,
                    currency=currency,
                    break_type="missing_internal",
                    external_balance=external_balance.balance if external_balance else None,
                    difference=external_balance.balance if external_balance else Decimal("0"),
                    severity=FindingSeverity.HIGH,
                )
            )
            continue
        if external_balance is None:
            breaks.append(
                CashBreak(
                    account=account,
                    currency=currency,
                    break_type="missing_external",
                    internal_balance=internal_balance.balance,
                    difference=internal_balance.balance,
                    severity=FindingSeverity.HIGH,
                )
            )
            continue

        difference = money(internal_balance.balance - external_balance.balance)
        if abs(difference) > tolerance:
            breaks.append(
                CashBreak(
                    account=account,
                    currency=currency,
                    break_type="balance_mismatch",
                    internal_balance=internal_balance.balance,
                    external_balance=external_balance.balance,
                    difference=difference,
                    severity=FindingSeverity.HIGH,
                )
            )
        else:
            matched += 1

    return CashReconciliationResult(
        breaks=breaks,
        matched_count=matched,
        internal_count=len(internal),
        external_count=len(external),
    )


# --- Trades ------------------------------------------------------------------------------------


class Trade(BaseModel):
    trade_id: str
    fund: str
    security_id: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    trade_date: date
    settlement_date: date | None = None
    status: Literal["unsettled", "settled", "cancelled"] = "unsettled"

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def _normalise_money(cls, value: Any) -> Decimal:
        return money(value)

    @field_validator("side", mode="before")
    @classmethod
    def _normalise_side(cls, value: Any) -> str:
        return _text(value).lower()


class TradeBreak(BaseModel):
    trade_id: str
    security_id: str | None = None
    break_type: Literal[
        "missing_internal",
        "missing_external",
        "side_mismatch",
        "quantity_mismatch",
        "price_mismatch",
    ]
    internal_side: str | None = None
    external_side: str | None = None
    internal_quantity: Decimal | None = None
    external_quantity: Decimal | None = None
    internal_price: Decimal | None = None
    external_price: Decimal | None = None
    severity: FindingSeverity


class TradeReconciliationResult(BaseModel):
    breaks: list[TradeBreak] = Field(default_factory=list)
    matched_count: int = 0
    internal_count: int = 0
    external_count: int = 0

    def to_exceptions(self) -> list[ExceptionItem]:
        exceptions = []
        for item in self.breaks:
            impact = Decimal("0")
            if item.internal_quantity is not None and item.internal_price is not None:
                impact = abs(money(item.internal_quantity * item.internal_price))
            elif item.external_quantity is not None and item.external_price is not None:
                impact = abs(money(item.external_quantity * item.external_price))
            exceptions.append(
                ExceptionItem(
                    category="trade",
                    code=f"trade.{item.break_type}",
                    key=item.trade_id,
                    title=f"Trade {item.trade_id}: {item.break_type.replace('_', ' ')}",
                    detail=(
                        f"Internal {item.internal_side or '-'} {item.internal_quantity or '-'} @ "
                        f"{item.internal_price or '-'} vs external {item.external_side or '-'} "
                        f"{item.external_quantity or '-'} @ {item.external_price or '-'}."
                    ),
                    severity=item.severity,
                    impact_amount=impact,
                )
            )
        return exceptions


def parse_trades(content: bytes) -> list[Trade]:
    """Parse a flexible JSON trade export: a top-level array, or an object with a ``trades``
    array. Reused by both reconcile_trades (internal vs external) and detect_unsettled_trades
    (a single blotter)."""

    return [Trade.model_validate(row) for row in _load_json(content, "trades")]


def reconcile_trades(
    internal: list[Trade],
    external: list[Trade],
    *,
    quantity_tolerance: Decimal = DEFAULT_QUANTITY_TOLERANCE,
    price_tolerance: Decimal = DEFAULT_PRICE_TOLERANCE,
) -> TradeReconciliationResult:
    """Compare an internal trade blotter against an external one (broker/custodian
    confirmations), matched by trade_id."""

    internal_by_id = {trade.trade_id: trade for trade in internal}
    external_by_id = {trade.trade_id: trade for trade in external}
    breaks: list[TradeBreak] = []
    matched = 0

    for trade_id in sorted(set(internal_by_id) | set(external_by_id)):
        internal_trade = internal_by_id.get(trade_id)
        external_trade = external_by_id.get(trade_id)
        if internal_trade is None:
            breaks.append(
                TradeBreak(
                    trade_id=trade_id,
                    security_id=external_trade.security_id if external_trade else None,
                    break_type="missing_internal",
                    external_side=external_trade.side if external_trade else None,
                    external_quantity=external_trade.quantity if external_trade else None,
                    external_price=external_trade.price if external_trade else None,
                    severity=FindingSeverity.HIGH,
                )
            )
            continue
        if external_trade is None:
            breaks.append(
                TradeBreak(
                    trade_id=trade_id,
                    security_id=internal_trade.security_id,
                    break_type="missing_external",
                    internal_side=internal_trade.side,
                    internal_quantity=internal_trade.quantity,
                    internal_price=internal_trade.price,
                    severity=FindingSeverity.HIGH,
                )
            )
            continue

        common = {
            "trade_id": trade_id,
            "security_id": internal_trade.security_id,
            "internal_side": internal_trade.side,
            "external_side": external_trade.side,
            "internal_quantity": internal_trade.quantity,
            "external_quantity": external_trade.quantity,
            "internal_price": internal_trade.price,
            "external_price": external_trade.price,
        }
        if internal_trade.side != external_trade.side:
            breaks.append(
                TradeBreak(**common, break_type="side_mismatch", severity=FindingSeverity.HIGH)
            )
        elif abs(money(internal_trade.quantity - external_trade.quantity)) > quantity_tolerance:
            breaks.append(
                TradeBreak(**common, break_type="quantity_mismatch", severity=FindingSeverity.HIGH)
            )
        elif abs(money(internal_trade.price - external_trade.price)) > price_tolerance:
            breaks.append(
                TradeBreak(**common, break_type="price_mismatch", severity=FindingSeverity.HIGH)
            )
        else:
            matched += 1

    return TradeReconciliationResult(
        breaks=breaks,
        matched_count=matched,
        internal_count=len(internal),
        external_count=len(external),
    )


# --- Stale prices --------------------------------------------------------------------------------


class PriceRecord(BaseModel):
    security_id: str
    security_name: str | None = None
    price: Decimal
    price_date: date
    currency: str = "USD"

    @field_validator("price", mode="before")
    @classmethod
    def _normalise_price(cls, value: Any) -> Decimal:
        return money(value)


class StalePriceFinding(BaseModel):
    security_id: str
    security_name: str | None = None
    price_date: date
    age_days: int
    severity: FindingSeverity

    def to_exception(self) -> ExceptionItem:
        return ExceptionItem(
            category="stale_price",
            code="stale_price.overdue",
            key=self.security_id,
            title=f"{self.security_name or self.security_id}: price is {self.age_days} day(s) old",
            detail=f"Last priced {self.price_date.isoformat()}, {self.age_days} day(s) before the as-of date.",
            severity=self.severity,
        )


def parse_prices(content: bytes) -> list[PriceRecord]:
    """Parse a flexible JSON price export: a top-level array, or an object with a ``prices``
    array."""

    return [PriceRecord.model_validate(row) for row in _load_json(content, "prices")]


def detect_stale_prices(
    prices: list[PriceRecord], *, as_of: date, max_age_days: int = 3
) -> list[StalePriceFinding]:
    """Flag any price whose price_date is more than max_age_days before as_of. Severity escalates
    to HIGH beyond twice the threshold (a price that is merely a day late is a WARNING; a price
    that is a week old against a 3-day policy is a HIGH risk to the NAV)."""

    findings: list[StalePriceFinding] = []
    for price in prices:
        age_days = (as_of - price.price_date).days
        if age_days <= max_age_days:
            continue
        severity = FindingSeverity.HIGH if age_days > max_age_days * 2 else FindingSeverity.WARNING
        findings.append(
            StalePriceFinding(
                security_id=price.security_id,
                security_name=price.security_name,
                price_date=price.price_date,
                age_days=age_days,
                severity=severity,
            )
        )
    return sorted(findings, key=lambda finding: -finding.age_days)


# --- Unsettled trades ----------------------------------------------------------------------------


class UnsettledTradeFinding(BaseModel):
    trade_id: str
    security_id: str
    settlement_date: date
    days_overdue: int
    severity: FindingSeverity

    def to_exception(self) -> ExceptionItem:
        return ExceptionItem(
            category="unsettled_trade",
            code="unsettled_trade.overdue",
            key=self.trade_id,
            title=f"Trade {self.trade_id}: unsettled {self.days_overdue} day(s) past due",
            detail=(
                f"Expected settlement {self.settlement_date.isoformat()}, "
                f"{self.days_overdue} day(s) overdue."
            ),
            severity=self.severity,
        )


def detect_unsettled_trades(
    trades: list[Trade], *, as_of: date, grace_days: int = 3
) -> list[UnsettledTradeFinding]:
    """Flag trades still marked unsettled whose settlement_date has passed as_of. Severity
    escalates to HIGH once the trade is more than grace_days past its settlement date (the
    standard T+ settlement grace window)."""

    findings: list[UnsettledTradeFinding] = []
    for trade in trades:
        if trade.status != "unsettled" or trade.settlement_date is None:
            continue
        days_overdue = (as_of - trade.settlement_date).days
        if days_overdue <= 0:
            continue
        severity = FindingSeverity.HIGH if days_overdue > grace_days else FindingSeverity.WARNING
        findings.append(
            UnsettledTradeFinding(
                trade_id=trade.trade_id,
                security_id=trade.security_id,
                settlement_date=trade.settlement_date,
                days_overdue=days_overdue,
                severity=severity,
            )
        )
    return sorted(findings, key=lambda finding: -finding.days_overdue)


# --- Exposure breaches ---------------------------------------------------------------------------


class ExposureLimit(BaseModel):
    label: str
    scope: Literal["single_position", "issuer", "sector", "gross_exposure"]
    key: str | None = None
    max_percent_of_nav: Decimal

    @field_validator("max_percent_of_nav", mode="before")
    @classmethod
    def _normalise_percent(cls, value: Any) -> Decimal:
        return Decimal(str(value))


class ExposureBreach(BaseModel):
    limit_label: str
    scope: str
    key: str | None
    exposure_amount: Decimal
    exposure_percent: Decimal
    limit_percent: Decimal
    severity: FindingSeverity

    def to_exception(self) -> ExceptionItem:
        return ExceptionItem(
            category="exposure_breach",
            code=f"exposure_breach.{self.scope}",
            key=self.key,
            title=f"{self.limit_label}: {self.exposure_percent}% exceeds the {self.limit_percent}% limit",
            detail=f"Exposure of {self.exposure_amount} is {self.exposure_percent}% of NAV.",
            severity=self.severity,
        )


def parse_exposure_limits(content: bytes) -> list[ExposureLimit]:
    """Parse a flexible JSON exposure-limit set: a top-level array, or an object with a
    ``limits`` array."""

    return [ExposureLimit.model_validate(row) for row in _load_json(content, "limits")]


def detect_exposure_breaches(
    positions: list[Position], *, nav: Decimal, limits: list[ExposureLimit]
) -> list[ExposureBreach]:
    """Compute exposure against each supplied limit and flag any breach.

    single_position and gross_exposure limits apply fund-wide; a single_position limit checks
    every position independently (each position is its own key), gross_exposure sums the absolute
    market value of every position (total leverage/usage of NAV) as one check. issuer and sector
    limits group positions by that field: a limit with a key checks only that issuer/sector, a
    limit with no key is a "no single issuer/sector may exceed X%" rule checked against every
    group found in the positions.
    """

    if nav == 0:
        raise ValueError("NAV must be non-zero to compute exposure percentages.")

    breaches: list[ExposureBreach] = []

    def _percent(amount: Decimal) -> Decimal:
        return (amount / nav * Decimal("100")).quantize(Decimal("0.01"))

    for limit in limits:
        if limit.scope == "gross_exposure":
            total = sum(
                (abs(position.resolved_market_value) for position in positions), Decimal("0")
            )
            percent = _percent(total)
            if percent > limit.max_percent_of_nav:
                breaches.append(
                    ExposureBreach(
                        limit_label=limit.label,
                        scope=limit.scope,
                        key=None,
                        exposure_amount=money(total),
                        exposure_percent=percent,
                        limit_percent=limit.max_percent_of_nav,
                        severity=FindingSeverity.HIGH,
                    )
                )
        elif limit.scope == "single_position":
            for position in positions:
                percent = _percent(abs(position.resolved_market_value))
                if percent > limit.max_percent_of_nav:
                    breaches.append(
                        ExposureBreach(
                            limit_label=limit.label,
                            scope=limit.scope,
                            key=position.security_id,
                            exposure_amount=position.resolved_market_value,
                            exposure_percent=percent,
                            limit_percent=limit.max_percent_of_nav,
                            severity=FindingSeverity.HIGH,
                        )
                    )
        else:  # issuer or sector
            field = limit.scope
            totals: dict[str, Decimal] = {}
            for position in positions:
                group_key = getattr(position, field)
                if not group_key:
                    continue
                if limit.key is not None and group_key != limit.key:
                    continue
                totals[group_key] = totals.get(group_key, Decimal("0")) + abs(
                    position.resolved_market_value
                )
            for group_key, total in totals.items():
                percent = _percent(total)
                if percent > limit.max_percent_of_nav:
                    breaches.append(
                        ExposureBreach(
                            limit_label=limit.label,
                            scope=limit.scope,
                            key=group_key,
                            exposure_amount=money(total),
                            exposure_percent=percent,
                            limit_percent=limit.max_percent_of_nav,
                            severity=FindingSeverity.HIGH,
                        )
                    )

    return sorted(breaches, key=lambda breach: -breach.exposure_percent)


# --- Prioritise exceptions ------------------------------------------------------------------------


def prioritise_exceptions(
    exceptions: list[ExceptionItem], *, top_n: int | None = None
) -> list[ExceptionItem]:
    """Rank exceptions from any of the checks above by severity (HIGH first, then WARNING, then
    INFO/PASS) and, within a severity, by impact_amount (materiality) descending. Domain-agnostic
    by design: it never inspects category-specific fields, only the common severity/impact_amount
    shape every check above already produces via its to_exceptions()/to_exception() method.
    """

    severity_rank = {
        FindingSeverity.HIGH: 0,
        FindingSeverity.WARNING: 1,
        FindingSeverity.INFO: 2,
        FindingSeverity.PASS: 3,
    }
    ranked = sorted(
        exceptions,
        key=lambda item: (severity_rank.get(item.severity, 99), -item.impact_amount),
    )
    return ranked if top_n is None else ranked[:top_n]
