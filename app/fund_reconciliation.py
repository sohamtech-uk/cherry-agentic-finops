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
``ExceptionItem`` records from any of the other eight checks (each result type has a
``to_exceptions()`` method) and ranks them by severity then materiality, the same ordering
``app.nav_exceptions.group_exceptions_by_root_cause`` uses for NAV-level findings.

The last two checks (management fee validation, expense allocation validation) extend this family
down a different axis from the first six: instead of comparing two records of the same shape
(internal vs external), they compare an administrator-reported figure against a *rule* — the
governing fee rate/basis or the fund manager's own expected allocation — so a break can be flagged
even when there is nothing else to diff against.

``attach_evidence`` is the other domain-agnostic function here: it stamps document lineage (source
filename, SHA-256 hash, and the exception's own key as a locator) onto an already-produced
exceptions list, so "why did Cherry flag this" traces back to the exact uploaded file(s) rather
than a bare in-memory finding. Like ``prioritise_exceptions``, it works on the common
``ExceptionItem`` shape and never recomputes a figure.
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


class EvidenceSource(BaseModel):
    """One input file's identity, as supplied by the caller that actually read it. This module
    never sees a raw file path or its bytes -- only the parsed records -- so a source's filename
    and hash always come from outside (typically ``app.agent_tools``'s file-reading layer)."""

    source_id: str
    filename: str
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class EvidenceRef(BaseModel):
    """One document-lineage pointer for a single exception: which source produced it, that
    source's tamper-evident SHA-256 hash (the same file re-hashes to the same value; a changed
    file does not), and where within it the finding sits -- the same key used to match records for
    this check (an account, security_id, trade_id, investor or expense_id)."""

    source_id: str
    filename: str
    sha256: str
    locator: str | None = None


class ExceptionItem(BaseModel):
    """A single triageable finding from any fund-reconciliation check, in a common shape so
    ``prioritise_exceptions`` can rank findings from different checks together."""

    category: Literal[
        "position",
        "cash",
        "trade",
        "stale_price",
        "unsettled_trade",
        "exposure_breach",
        "management_fee",
        "expense_allocation",
        "statement",
        "data_quality",
    ]
    code: str
    key: str | None = None
    title: str
    detail: str
    severity: FindingSeverity
    impact_amount: Decimal = Decimal("0")
    evidence: list[EvidenceRef] = Field(default_factory=list)


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


# --- Management fee validation ------------------------------------------------------------------


FeeBasis = Literal["committed_capital", "invested_capital", "called_capital", "net_asset_value"]


class FeeRule(BaseModel):
    investor: str
    fee_rate: Decimal
    fee_basis: FeeBasis
    source: str | None = None

    @field_validator("fee_rate", mode="before")
    @classmethod
    def _normalise_rate(cls, value: Any) -> Decimal:
        return Decimal(str(value))


class AdministratorFeeLine(BaseModel):
    investor: str
    fee_basis: FeeBasis
    basis_amount: Decimal
    reported_fee: Decimal

    @field_validator("basis_amount", "reported_fee", mode="before")
    @classmethod
    def _normalise_money(cls, value: Any) -> Decimal:
        return money(value)


class FeeBreak(BaseModel):
    investor: str
    break_type: Literal["rule_unavailable", "basis_mismatch", "amount_mismatch"]
    rule_fee_rate: Decimal | None = None
    rule_fee_basis: FeeBasis | None = None
    administrator_fee_basis: FeeBasis
    basis_amount: Decimal
    reported_fee: Decimal
    expected_fee: Decimal | None = None
    difference: Decimal | None = None
    severity: FindingSeverity

    def to_exception(self) -> ExceptionItem:
        label = self.investor
        if self.break_type == "rule_unavailable":
            detail = (
                f"No fee rule was supplied for {label}; the reported fee of {self.reported_fee} "
                f"on a {self.administrator_fee_basis.replace('_', ' ')} basis could not be "
                "independently checked."
            )
        elif self.break_type == "basis_mismatch":
            rule_basis = (self.rule_fee_basis or "?").replace("_", " ")
            admin_basis = self.administrator_fee_basis.replace("_", " ")
            detail = (
                f"The governing rule applies the fee to a {rule_basis} basis, but the "
                f"administrator applied it to a {admin_basis} basis ({self.basis_amount})."
            )
        else:
            detail = (
                f"Expected fee of {self.expected_fee} ({self.rule_fee_rate} x {self.basis_amount}) "
                f"does not match the administrator's reported fee of {self.reported_fee}."
            )
        return ExceptionItem(
            category="management_fee",
            code=f"management_fee.{self.break_type}",
            key=self.investor,
            title=f"{label}: management fee {self.break_type.replace('_', ' ')}",
            detail=detail,
            severity=self.severity,
            impact_amount=abs(self.difference) if self.difference is not None else Decimal("0"),
        )


class FeeValidationResult(BaseModel):
    breaks: list[FeeBreak] = Field(default_factory=list)
    matched_count: int = 0

    def to_exceptions(self) -> list[ExceptionItem]:
        return [item.to_exception() for item in self.breaks]


def parse_fee_rules(content: bytes) -> list[FeeRule]:
    """Parse a flexible JSON fee-rule set (LPA defaults or side-letter overrides): a top-level
    array, or an object with a ``fee_rules`` array."""

    return [FeeRule.model_validate(row) for row in _load_json(content, "fee_rules")]


def parse_administrator_fees(content: bytes) -> list[AdministratorFeeLine]:
    """Parse a flexible JSON administrator fee-calculation export: a top-level array, or an
    object with an ``administrator_fees`` array."""

    return [
        AdministratorFeeLine.model_validate(row)
        for row in _load_json(content, "administrator_fees")
    ]


def validate_management_fees(
    rules: list[FeeRule],
    administrator_fees: list[AdministratorFeeLine],
    *,
    tolerance: Decimal = DEFAULT_MONEY_TOLERANCE,
) -> FeeValidationResult:
    """Compare each administrator-calculated management fee against the governing fee rule (LPA
    default or side-letter override) for that investor, matched by investor name.

    Two independent break types beyond a missing rule: the administrator may have applied the fee
    to the wrong basis (e.g. committed capital instead of invested capital) even when the rate is
    right — flagged regardless of the resulting amount, because the wrong basis is wrong even when
    it happens not to move this period's number much — or the recomputed fee (basis_amount x rate)
    may simply disagree with what the administrator reported.
    """

    rules_by_investor = {rule.investor.casefold(): rule for rule in rules}
    breaks: list[FeeBreak] = []
    matched = 0

    for line in administrator_fees:
        rule = rules_by_investor.get(line.investor.casefold())
        if rule is None:
            breaks.append(
                FeeBreak(
                    investor=line.investor,
                    break_type="rule_unavailable",
                    administrator_fee_basis=line.fee_basis,
                    basis_amount=line.basis_amount,
                    reported_fee=line.reported_fee,
                    severity=FindingSeverity.WARNING,
                )
            )
            continue

        expected_fee = money(line.basis_amount * rule.fee_rate)
        difference = money(line.reported_fee - expected_fee)
        common = {
            "investor": line.investor,
            "rule_fee_rate": rule.fee_rate,
            "rule_fee_basis": rule.fee_basis,
            "administrator_fee_basis": line.fee_basis,
            "basis_amount": line.basis_amount,
            "reported_fee": line.reported_fee,
            "expected_fee": expected_fee,
            "difference": difference,
        }
        if line.fee_basis != rule.fee_basis:
            breaks.append(
                FeeBreak(**common, break_type="basis_mismatch", severity=FindingSeverity.HIGH)
            )
        elif abs(difference) > tolerance:
            breaks.append(
                FeeBreak(**common, break_type="amount_mismatch", severity=FindingSeverity.HIGH)
            )
        else:
            matched += 1

    return FeeValidationResult(breaks=breaks, matched_count=matched)


# --- Expense allocation validation ---------------------------------------------------------------


ExpenseCategory = Literal["fund", "management_company", "portfolio_company"]


class ExpectedExpenseAllocation(BaseModel):
    expense_id: str
    description: str | None = None
    amount: Decimal
    expected_category: ExpenseCategory
    portfolio_company: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _normalise_amount(cls, value: Any) -> Decimal:
        return money(value)


class AdministratorExpenseLine(BaseModel):
    expense_id: str
    description: str | None = None
    amount: Decimal
    allocated_category: ExpenseCategory
    portfolio_company: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _normalise_amount(cls, value: Any) -> Decimal:
        return money(value)


class ExpenseBreak(BaseModel):
    expense_id: str
    description: str | None = None
    break_type: Literal[
        "missing_internal", "missing_external", "category_mismatch", "amount_mismatch"
    ]
    expected_category: str | None = None
    allocated_category: str | None = None
    expected_portfolio_company: str | None = None
    allocated_portfolio_company: str | None = None
    internal_amount: Decimal | None = None
    external_amount: Decimal | None = None
    difference: Decimal
    severity: FindingSeverity

    def to_exception(self) -> ExceptionItem:
        label = self.description or self.expense_id
        if self.break_type == "missing_internal":
            detail = (
                f"The administrator allocated an expense ({label}) that is not present in the "
                "fund manager's expected allocation schedule."
            )
        elif self.break_type == "missing_external":
            detail = (
                f"The fund manager expected an allocation for {label} that the administrator's "
                "package does not contain."
            )
        elif self.break_type == "category_mismatch":
            expected = (self.expected_category or "?").replace("_", " ")
            allocated = (self.allocated_category or "?").replace("_", " ")
            detail = (
                f"Expected this expense to sit with the {expected}, but the administrator "
                f"allocated it to the {allocated}."
            )
        else:
            detail = f"Internal amount {self.internal_amount} vs administrator amount {self.external_amount}."
        return ExceptionItem(
            category="expense_allocation",
            code=f"expense_allocation.{self.break_type}",
            key=self.expense_id,
            title=f"{label}: {self.break_type.replace('_', ' ')}",
            detail=detail,
            severity=self.severity,
            impact_amount=abs(self.difference),
        )


class ExpenseAllocationResult(BaseModel):
    breaks: list[ExpenseBreak] = Field(default_factory=list)
    matched_count: int = 0
    internal_count: int = 0
    external_count: int = 0

    def to_exceptions(self) -> list[ExceptionItem]:
        return [item.to_exception() for item in self.breaks]


def parse_expected_expense_allocations(content: bytes) -> list[ExpectedExpenseAllocation]:
    """Parse a flexible JSON expected-allocation schedule (the fund manager's own record of which
    entity each expense belongs to): a top-level array, or an object with an
    ``expected_allocations`` array."""

    return [
        ExpectedExpenseAllocation.model_validate(row)
        for row in _load_json(content, "expected_allocations")
    ]


def parse_administrator_expenses(content: bytes) -> list[AdministratorExpenseLine]:
    """Parse a flexible JSON administrator expense-allocation export: a top-level array, or an
    object with an ``administrator_expenses`` array."""

    return [
        AdministratorExpenseLine.model_validate(row)
        for row in _load_json(content, "administrator_expenses")
    ]


def reconcile_expense_allocations(
    expected: list[ExpectedExpenseAllocation],
    administrator: list[AdministratorExpenseLine],
    *,
    amount_tolerance: Decimal = DEFAULT_MONEY_TOLERANCE,
) -> ExpenseAllocationResult:
    """Compare the fund manager's expected expense allocation (which entity each expense belongs
    to — the fund, the management company, or a named portfolio company) against how the
    administrator actually allocated it, matched by expense_id.

    This is the deterministic check for "which expenses belong to the management company, which
    belong to the fund, which belong to portfolio companies" — a category mismatch is flagged as
    HIGH regardless of amount, since a misallocated expense is a control break even when the
    figure itself is immaterial; an amount-only difference on an otherwise correctly categorised
    expense is a WARNING.
    """

    expected_by_id = {line.expense_id: line for line in expected}
    administrator_by_id = {line.expense_id: line for line in administrator}
    breaks: list[ExpenseBreak] = []
    matched = 0

    for expense_id in sorted(set(expected_by_id) | set(administrator_by_id)):
        expected_line = expected_by_id.get(expense_id)
        administrator_line = administrator_by_id.get(expense_id)
        if expected_line is None:
            breaks.append(
                ExpenseBreak(
                    expense_id=expense_id,
                    description=administrator_line.description if administrator_line else None,
                    break_type="missing_internal",
                    allocated_category=(
                        administrator_line.allocated_category if administrator_line else None
                    ),
                    allocated_portfolio_company=(
                        administrator_line.portfolio_company if administrator_line else None
                    ),
                    external_amount=administrator_line.amount if administrator_line else None,
                    difference=administrator_line.amount if administrator_line else Decimal("0"),
                    severity=FindingSeverity.WARNING,
                )
            )
            continue
        if administrator_line is None:
            breaks.append(
                ExpenseBreak(
                    expense_id=expense_id,
                    description=expected_line.description,
                    break_type="missing_external",
                    expected_category=expected_line.expected_category,
                    expected_portfolio_company=expected_line.portfolio_company,
                    internal_amount=expected_line.amount,
                    difference=expected_line.amount,
                    severity=FindingSeverity.WARNING,
                )
            )
            continue

        description = expected_line.description or administrator_line.description
        category_mismatch = (
            expected_line.expected_category != administrator_line.allocated_category
            or (
                expected_line.expected_category == "portfolio_company"
                and (expected_line.portfolio_company or "").casefold()
                != (administrator_line.portfolio_company or "").casefold()
            )
        )
        amount_difference = money(expected_line.amount - administrator_line.amount)
        if category_mismatch:
            breaks.append(
                ExpenseBreak(
                    expense_id=expense_id,
                    description=description,
                    break_type="category_mismatch",
                    expected_category=expected_line.expected_category,
                    allocated_category=administrator_line.allocated_category,
                    expected_portfolio_company=expected_line.portfolio_company,
                    allocated_portfolio_company=administrator_line.portfolio_company,
                    internal_amount=expected_line.amount,
                    external_amount=administrator_line.amount,
                    difference=amount_difference,
                    severity=FindingSeverity.HIGH,
                )
            )
        elif abs(amount_difference) > amount_tolerance:
            breaks.append(
                ExpenseBreak(
                    expense_id=expense_id,
                    description=description,
                    break_type="amount_mismatch",
                    expected_category=expected_line.expected_category,
                    allocated_category=administrator_line.allocated_category,
                    internal_amount=expected_line.amount,
                    external_amount=administrator_line.amount,
                    difference=amount_difference,
                    severity=FindingSeverity.WARNING,
                )
            )
        else:
            matched += 1

    return ExpenseAllocationResult(
        breaks=breaks,
        matched_count=matched,
        internal_count=len(expected),
        external_count=len(administrator),
    )


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


# --- Document lineage ------------------------------------------------------------------------


def attach_evidence(
    exceptions: list[ExceptionItem], *, sources: list[EvidenceSource]
) -> list[ExceptionItem]:
    """Stamp every exception with the document lineage for every source that fed the check that
    produced it: each source's filename and SHA-256 hash, plus the exception's own key as the
    locator (the record -- an account, security_id, trade_id, investor or expense_id -- the
    finding is about within that source).

    Domain-agnostic, like ``prioritise_exceptions``: it never re-derives a figure or a finding, and
    it does not decide which source is "responsible" for a break -- every source passed in is cited
    on every exception, because this module never sees which side of a two-file comparison a given
    caller believes is at fault. Call it once per check, passing every source file that check read
    (both sides of a reconciliation, or the single file for a single-source detection); the caller
    (typically ``app.agent_tools``, which is where a file's bytes and path are actually available)
    is responsible for supplying each source's filename and SHA-256 hash.
    """

    if not sources:
        return exceptions
    return [
        item.model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        source_id=source.source_id,
                        filename=source.filename,
                        sha256=source.sha256,
                        locator=item.key,
                    )
                    for source in sources
                ]
            }
        )
        for item in exceptions
    ]
