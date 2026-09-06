"""Agentic investigation over a prioritised fund-operations exception queue.

Problem this closes: ``prioritise_exceptions`` (app.fund_reconciliation) already ranks a combined
"position break / cash break / trade break / stale price / unsettled trade / exposure breach / fee
discrepancy / expense discrepancy" queue by severity then materiality. What was missing is the next
step a fund manager actually wants — an agent that picks the highest-risk exception up off that
queue, correlates it against every other exception sharing the same key (the same investor,
security, account or trade — a strong signal they are one underlying incident rather than several
independent ones), and returns a recommended owner, action and escalation step.

Same deterministic boundary as every other control in this codebase: this never invents a root
cause, a document reference or a figure. "Related" means "already present in the same prioritised
list under the same key" — a lookup, not a judgement call — and the recommended owner/action/next
step are a fixed table keyed by category and severity, not an LLM's opinion. The agent's job is to
call this, then explain the result; this module's job is to decide it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.fund_reconciliation import EvidenceRef, ExceptionItem, prioritise_exceptions
from app.private_markets import FindingSeverity

NextStep = Literal[
    "escalate_immediately", "assign_and_monitor", "request_evidence", "accept_and_close"
]

_OWNER_BY_CATEGORY: dict[str, str] = {
    "position": "Fund controller",
    "cash": "Treasury / fund controller",
    "trade": "Trading desk / operations",
    "stale_price": "Valuation team",
    "unsettled_trade": "Trading desk / operations",
    "exposure_breach": "Portfolio manager / risk",
    "management_fee": "Investor relations",
    "expense_allocation": "Fund controller",
    "statement": "Fund reporting / fund controller",
    "data_quality": "Fund operations",
}

_ACTION_BY_CATEGORY: dict[str, str] = {
    "position": (
        "Trace the position break to the custodian/administrator statement and correct the "
        "internal record, or request an administrator correction."
    ),
    "cash": (
        "Trace the cash break to the underlying bank statement transaction and correct the "
        "internal ledger, or request an administrator correction."
    ),
    "trade": "Confirm the trade details with the broker/administrator and correct whichever side is wrong.",
    "stale_price": "Obtain a current price for the security before the NAV is released.",
    "unsettled_trade": "Follow up on settlement status with the broker/custodian.",
    "exposure_breach": (
        "Confirm the breach with the portfolio manager and document either a waiver or a "
        "rebalancing plan."
    ),
    "management_fee": (
        "Correct the fee calculation to the governing rule's rate and basis, or obtain the "
        "missing rule if none was supplied."
    ),
    "expense_allocation": (
        "Reclassify the expense to the entity named in the fund manager's expected allocation "
        "schedule."
    ),
    "statement": (
        "Compare the changed disclosure and repeated dates with supporting period evidence, then "
        "confirm or correct the current-period statement before release."
    ),
    "data_quality": (
        "Supply or correct the evidence named by the control plan, then rerun the deterministic "
        "control before making a financial decision."
    ),
}

_DEFAULT_OWNER = "Fund controller"
_DEFAULT_ACTION = "Investigate the underlying record and correct it, or escalate for review."


class RelatedException(BaseModel):
    category: str
    code: str
    key: str | None = None
    title: str
    severity: FindingSeverity
    impact_amount: Decimal
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Investigation(BaseModel):
    exception: ExceptionItem
    related_exceptions: list[RelatedException] = Field(default_factory=list)
    likely_root_cause: str
    recommended_owner: str
    recommended_action: str
    next_step: NextStep
    rationale: str


def investigate_exception(
    exceptions: list[ExceptionItem],
    *,
    code: str | None = None,
    key: str | None = None,
    target_exception: ExceptionItem | None = None,
) -> Investigation:
    """Investigate one exception from a combined exception queue: the highest-priority one by
    default, or a specific one selected by its code or key.

    Finds every other exception in the same queue sharing the target's key (a likely shared root
    cause rather than an independent issue), and derives a recommended owner, action and escalation
    step from the target's category and severity plus whether the related exceptions span more
    than one category (a cross-category cluster — e.g. a cash break and a trade break on the same
    account — is treated as more urgent than an isolated one).
    """

    if not exceptions:
        raise ValueError("No exceptions supplied to investigate.")

    ranked = prioritise_exceptions(exceptions)
    if target_exception is not None:
        target = next((item for item in ranked if item is target_exception), None)
        if target is None:
            raise ValueError("The target exception was not supplied in the exception queue.")
    elif code is not None:
        target = next((item for item in ranked if item.code == code), None)
        if target is None:
            raise ValueError(f"No exception with code {code!r} was supplied.")
    elif key is not None:
        target = next((item for item in ranked if item.key == key), None)
        if target is None:
            raise ValueError(f"No exception with key {key!r} was supplied.")
    else:
        target = ranked[0]

    related = [
        RelatedException(
            category=item.category,
            code=item.code,
            key=item.key,
            title=item.title,
            severity=item.severity,
            impact_amount=item.impact_amount,
            evidence=item.evidence,
        )
        for item in ranked
        if item is not target and target.key is not None and item.key == target.key
    ]

    distinct_categories = {target.category, *(item.category for item in related)}
    if related:
        other_categories = sorted(distinct_categories - {target.category})
        cluster_note = (
            f" {len(related)} other exception(s) share key {target.key!r}"
            + (f" across {', '.join(other_categories)}" if other_categories else "")
            + " — investigate as one incident rather than independently."
        )
        likely_root_cause = target.detail + cluster_note
    else:
        likely_root_cause = target.detail

    if target.severity == FindingSeverity.HIGH and len(distinct_categories) > 1:
        next_step: NextStep = "escalate_immediately"
        rationale = (
            "HIGH severity with related exceptions in more than one category: this looks like a "
            "single incident touching multiple records, not an isolated break."
        )
    elif target.severity == FindingSeverity.HIGH:
        next_step = "assign_and_monitor"
        rationale = "HIGH severity but isolated to this key; assign to the responsible owner and track to resolution."
    elif target.severity == FindingSeverity.WARNING:
        next_step = "request_evidence"
        rationale = "WARNING severity: not yet confirmed as a break; request supporting evidence before deciding an action."
    else:
        next_step = "accept_and_close"
        rationale = "Neither HIGH nor WARNING severity; no further action required unless new evidence arrives."

    return Investigation(
        exception=target,
        related_exceptions=related,
        likely_root_cause=likely_root_cause,
        recommended_owner=_OWNER_BY_CATEGORY.get(target.category, _DEFAULT_OWNER),
        recommended_action=_ACTION_BY_CATEGORY.get(target.category, _DEFAULT_ACTION),
        next_step=next_step,
        rationale=rationale,
    )
