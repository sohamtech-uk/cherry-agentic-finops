"""NAV Quality Controller — Exception / Root-Cause grouping.

Problem: a flat list of failed checks ("37 errors") makes a fund manager triage everything
manually before sending anything back to the administrator. This module groups a
``NAVReviewReport``'s findings into root causes — one balance-sheet break, one NAV-bridge break,
one break per affected investor's capital account — each carrying every related finding code and
a computed materiality (``impact_amount``), instead of reporting each symptom independently.

Deterministic by design, matching every other check in this codebase: this only reads figures
already computed by ``app.nav_quality.review_nav_quality`` (``NAVReviewReport``) and regroups them.
It never recomputes a figure, calls an LLM, or changes a finding's severity. Root causes are sorted
by impact (highest materiality first) so the highest-value fix surfaces first.

Kept in a separate module from ``app.nav_quality`` to avoid a circular import: this module imports
types from ``app.nav_quality``, so ``app.nav_quality`` cannot import this one back. Callers (the
FastAPI router, the ADK agent tool) call ``group_exceptions_by_root_cause`` as an explicit second
step after ``review_nav_quality``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.nav_quality import NAVFinding, NAVReviewReport
from app.private_markets import FindingSeverity, money

RootCauseCategory = Literal["balance_sheet", "nav_bridge", "investor_capital"]

_BALANCE_SHEET_CODES = {"balance_sheet.footing_mismatch", "balance_sheet.ledger_mismatch"}
_NAV_BRIDGE_CODES = {"nav_bridge.does_not_foot", "nav.independent_recalculation_mismatch"}
_INVESTOR_ISSUE_CODES = {
    "investor_capital.ledger_mismatch",
    "side_letter.rule_violation",
    "side_letter.evidence_incomplete",
    "side_letter.rule_unsupported",
    "side_letter.missing_management_fee",
}


class RootCauseGroup(BaseModel):
    code: str
    category: RootCauseCategory
    investor: str | None = None
    title: str
    summary: str
    severity: FindingSeverity
    impact_amount: Decimal
    related_finding_codes: list[str] = Field(default_factory=list)
    recommended_owner: str
    recommended_action: str


def _group_severity(findings: list[NAVFinding]) -> FindingSeverity:
    if any(finding.severity == FindingSeverity.HIGH for finding in findings):
        return FindingSeverity.HIGH
    return FindingSeverity.WARNING


def _balance_sheet_root_cause(report: NAVReviewReport) -> RootCauseGroup | None:
    present = {finding.code for finding in report.findings} & _BALANCE_SHEET_CODES
    if not present:
        return None
    findings = [finding for finding in report.findings if finding.code in present]
    bs = report.balance_sheet
    impact = abs(bs.reported_equity - bs.footed_equity)
    if bs.ledger_assets is not None and bs.ledger_liabilities is not None:
        ledger_equity = bs.ledger_assets - bs.ledger_liabilities
        impact = max(impact, abs(bs.reported_equity - ledger_equity))
    detail = "Assets, liabilities and reported equity do not tie out"
    if "balance_sheet.ledger_mismatch" in present:
        detail += ", and disagree with the independent source ledger"
    return RootCauseGroup(
        code="root_cause.balance_sheet_break",
        category="balance_sheet",
        title="Balance sheet does not reconcile",
        summary=detail + ".",
        severity=_group_severity(findings),
        impact_amount=money(impact),
        related_finding_codes=sorted(present),
        recommended_owner="Fund controller",
        recommended_action=(
            "Trace assets, liabilities and equity to source and correct the NAV pack before "
            "resubmission."
        ),
    )


def _nav_bridge_root_cause(report: NAVReviewReport) -> RootCauseGroup | None:
    present = {finding.code for finding in report.findings} & _NAV_BRIDGE_CODES
    if not present:
        return None
    findings = [finding for finding in report.findings if finding.code in present]
    bridge = report.nav_bridge
    impact = abs(bridge.reported_closing_nav - bridge.bridge_calculated_closing_nav)
    if bridge.ledger_closing_nav is not None:
        impact = max(impact, abs(bridge.reported_closing_nav - bridge.ledger_closing_nav))
    detail = "Opening NAV plus reported movements does not tie to the reported closing NAV"
    if "nav.independent_recalculation_mismatch" in present:
        detail += ", and an independent recalculation from the source ledger disagrees with it too"
    return RootCauseGroup(
        code="root_cause.nav_bridge_break",
        category="nav_bridge",
        title="NAV bridge does not reconcile",
        summary=detail + ".",
        severity=_group_severity(findings),
        impact_amount=money(impact),
        related_finding_codes=sorted(present),
        recommended_owner="Fund controller",
        recommended_action=(
            "Reconcile opening NAV, movements and closing NAV against the source ledger before "
            "returning the pack to the administrator."
        ),
    )


def _investor_root_causes(report: NAVReviewReport) -> list[RootCauseGroup]:
    by_investor: dict[str, list[NAVFinding]] = {}
    for finding in report.findings:
        if finding.investor and finding.code in _INVESTOR_ISSUE_CODES:
            by_investor.setdefault(finding.investor, []).append(finding)

    checks_by_investor = {check.investor: check for check in report.investor_reconciliation}
    groups: list[RootCauseGroup] = []
    for investor, findings in by_investor.items():
        check = checks_by_investor.get(investor)
        impact = Decimal("0")
        if check is not None:
            if check.ledger_capital is not None:
                impact = max(impact, abs(check.reported_capital - check.ledger_capital))
            if check.rule_adjusted_expected is not None:
                impact = max(impact, abs(check.reported_capital - check.rule_adjusted_expected))
        groups.append(
            RootCauseGroup(
                code=f"root_cause.investor_capital.{investor}",
                category="investor_capital",
                investor=investor,
                title=f"{investor}: capital account requires correction",
                summary=(
                    f"{len(findings)} related finding(s) trace back to this investor's capital "
                    "account."
                ),
                severity=_group_severity(findings),
                impact_amount=money(impact),
                related_finding_codes=sorted({finding.code for finding in findings}),
                recommended_owner="Investor relations",
                recommended_action=(
                    "Correct this investor's capital account, applying any side-letter terms and "
                    "confirming contract evidence, before the NAV is released."
                ),
            )
        )
    return groups


def group_exceptions_by_root_cause(report: NAVReviewReport) -> list[RootCauseGroup]:
    """Group a NAV review's findings into root causes, ranked by materiality (highest first).

    Three category shapes, matching the checks in ``review_nav_quality``:
    one balance-sheet-break group, one NAV-bridge-break group, and one group per investor whose
    capital account has an open finding (a ledger mismatch, or a side-letter rule that was
    violated, unsupported, or could not be validated). A HIGH-severity finding anywhere in a group
    makes the whole group HIGH; a group of only WARNING findings stays WARNING. Findings that
    aren't part of any of the three shapes (there are none today) are simply not grouped.
    """

    groups: list[RootCauseGroup] = []
    balance_sheet_group = _balance_sheet_root_cause(report)
    if balance_sheet_group is not None:
        groups.append(balance_sheet_group)
    nav_bridge_group = _nav_bridge_root_cause(report)
    if nav_bridge_group is not None:
        groups.append(nav_bridge_group)
    groups.extend(_investor_root_causes(report))

    groups.sort(
        key=lambda group: (
            group.severity != FindingSeverity.HIGH,
            -group.impact_amount,
        )
    )
    return groups
