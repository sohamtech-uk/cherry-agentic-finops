from __future__ import annotations

import csv
import hashlib
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.contracts import (
    ContractCitation,
    ContractDocumentSummary,
    ContractDocumentType,
    ContractRepository,
    InvestorRuleResult,
    RuleStatus,
)

TWOPLACES = Decimal("0.01")
DEMO_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "synthetic_side_letter_demo"
)
DEMO_FUND_NAME = "Cherry Demonstration Fund I LP"
DEMO_CALCULATION_DATE = date(2026, 9, 5)


class ContractDecision(StrEnum):
    PASS = "pass"
    REVIEW_REQUIRED = "review_required"
    EVIDENCE_REQUIRED = "evidence_required"


class ContractInvestor(BaseModel):
    investor_id: str
    investor_name: str
    commitment: Decimal
    currency: str = "GBP"

    @field_validator("commitment", mode="before")
    @classmethod
    def normalise_commitment(cls, value: object) -> Decimal:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class ObservedFeeCall(BaseModel):
    investor_id: str
    investor_name: str
    calculation_date: date
    base_investment_contribution: Decimal
    management_fee: Decimal
    total_cash_payable: Decimal
    currency: str = "GBP"

    @field_validator(
        "base_investment_contribution",
        "management_fee",
        "total_cash_payable",
        mode="before",
    )
    @classmethod
    def normalise_money(cls, value: object) -> Decimal:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class ContractRuleView(BaseModel):
    rule_id: str
    rule_type: str
    title: str
    scope: Literal["fund_default", "investor_specific"]
    investor_name: str | None = None
    value: str
    effective_date: date
    explicit_override: bool
    source: ContractCitation


class ResolvedContractRule(BaseModel):
    investor_id: str
    investor_name: str
    selected_rule_id: str
    default_rule_id: str
    override_rule_id: str | None = None
    resolution_reason: str
    decision: ContractDecision
    citations: list[ContractCitation]


class FeeCallCalculation(BaseModel):
    investor_id: str
    investor_name: str
    status: ContractDecision
    currency: str
    commitment: Decimal
    quarterly_fee_rate: Decimal
    calculated_management_fee: Decimal
    base_investment_contribution: Decimal
    expected_investment_component: Decimal
    expected_fee_component: Decimal
    expected_total_cash_payable: Decimal
    observed_total_cash_payable: Decimal
    variance: Decimal
    rule_source: Literal["lpa", "side_letter"]
    finding_codes: list[str] = Field(default_factory=list)


class ContractFinding(BaseModel):
    code: str
    severity: Literal["pass", "info", "warning", "high"]
    title: str
    detail: str
    investor_name: str
    expected: str | None = None
    observed: str | None = None
    source_rule_ids: list[str] = Field(default_factory=list)


class ContractWorkItem(BaseModel):
    priority: Literal["normal", "high"]
    owner: str
    title: str
    instruction: str
    finding_code: str


class ContractAnalysis(BaseModel):
    decision: ContractDecision
    fund_name: str
    calculation_date: date
    investor_count: int
    non_standard_investor_count: int
    rules_extracted: int
    rules_applied: int
    conflicts_open: int
    potential_overcall: Decimal
    findings: list[ContractFinding]
    resolved_rules: list[ResolvedContractRule]
    calculation_results: list[FeeCallCalculation]
    work_items: list[ContractWorkItem]
    financial_boundary: str = (
        "Decision support and contract-informed financial validation only; "
        "no payment initiation and no legal advice."
    )


class ContractEvidence(BaseModel):
    document_sha256: dict[str, str]
    workbook_sha256: dict[str, str]
    fixture_manifest_sha256: str


class ContractDemoResponse(BaseModel):
    workflow_type: Literal["contract_intelligence"] = "contract_intelligence"
    workflow_version: str = "contract-fee-control-v1"
    synthetic: Literal[True] = True
    sponsor_native: Literal[False] = False
    context_source: str = "Ylookup Call 1 — NAV workflow review"
    message: str = (
        "Synthetic contract fixture grounded in the side-letter fee problem described in "
        "Ylookup Call 1. No sponsor contract document was supplied."
    )
    documents: list[ContractDocumentSummary]
    rules: list[ContractRuleView]
    analysis: ContractAnalysis
    evidence: ContractEvidence


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _rule_view(
    *,
    rule_id: str,
    title: str,
    scope: Literal["fund_default", "investor_specific"],
    value: str,
    effective_date: date,
    explicit_override: bool,
    source: ContractCitation,
    investor_name: str | None = None,
) -> ContractRuleView:
    return ContractRuleView(
        rule_id=rule_id,
        rule_type="fee_call_treatment",
        title=title,
        scope=scope,
        investor_name=investor_name,
        value=value,
        effective_date=effective_date,
        explicit_override=explicit_override,
        source=source,
    )


def build_synthetic_side_letter_demo(
    fixture_root: Path = DEMO_ROOT,
) -> ContractDemoResponse:
    lpa_path = fixture_root / "lpa.md"
    side_letter_path = fixture_root / "side_letter_cedar.md"
    investor_path = fixture_root / "investor_register.csv"
    calculation_path = fixture_root / "admin_fee_calculation.csv"

    repository = ContractRepository()
    lpa = repository.ingest(
        content=lpa_path.read_bytes(),
        mime_type="text/markdown",
        file_name=lpa_path.name,
        document_type=ContractDocumentType.LPA,
        fund_name=DEMO_FUND_NAME,
    )
    side_letter = repository.ingest(
        content=side_letter_path.read_bytes(),
        mime_type="text/markdown",
        file_name=side_letter_path.name,
        document_type=ContractDocumentType.SIDE_LETTER,
        fund_name=DEMO_FUND_NAME,
        investor_name="Cedar Pension Trust",
    )
    lpa_citation = repository.extract_clause(lpa.document_id, "6.2").citation
    side_letter_citation = repository.extract_clause(side_letter.document_id, "3").citation

    default_rule = repository.get_investor_rule(
        investor_name="Orchard Institutional LP",
        rule_name="management_fee_offsets_called_capital",
        as_of_date=DEMO_CALCULATION_DATE,
        fund_name=DEMO_FUND_NAME,
    )
    override_rule = repository.get_investor_rule(
        investor_name="Cedar Pension Trust",
        rule_name="management_fee_offsets_called_capital",
        as_of_date=DEMO_CALCULATION_DATE,
        fund_name=DEMO_FUND_NAME,
    )
    rate_rule = repository.get_investor_rule(
        investor_name="Orchard Institutional LP",
        rule_name="management_fee_rate",
        as_of_date=DEMO_CALCULATION_DATE,
        fund_name=DEMO_FUND_NAME,
    )
    if default_rule.status != RuleStatus.FOUND or default_rule.value is not False:
        raise ValueError("Synthetic LPA fixture did not resolve to the expected default fee rule.")
    if override_rule.status != RuleStatus.FOUND or override_rule.value is not True:
        raise ValueError("Synthetic side letter did not resolve to the expected explicit override.")
    if (
        rate_rule.status != RuleStatus.FOUND
        or not isinstance(rate_rule.value, str)
        or not rate_rule.value.endswith("%")
    ):
        raise ValueError("Synthetic LPA fixture did not resolve to a deterministic fee rate.")
    if not lpa.effective_date or not side_letter.effective_date:
        raise ValueError("Synthetic contract fixtures must have explicit effective dates.")

    investors = {
        row["investor_id"]: ContractInvestor.model_validate(row) for row in _read_csv(investor_path)
    }
    observations = [ObservedFeeCall.model_validate(row) for row in _read_csv(calculation_path)]
    rate = Decimal(rate_rule.value.removesuffix("%")) / Decimal("100")
    calculations: list[FeeCallCalculation] = []
    findings: list[ContractFinding] = []
    resolved_rules: list[ResolvedContractRule] = []
    work_items: list[ContractWorkItem] = []

    for observation in observations:
        investor = investors.get(observation.investor_id)
        if investor is None or investor.investor_name != observation.investor_name:
            raise ValueError(
                f"Investor identity could not be bound exactly for {observation.investor_id}."
            )
        if observation.calculation_date != DEMO_CALCULATION_DATE:
            raise ValueError("Synthetic calculation date does not match the demo reporting date.")
        if observation.currency != investor.currency:
            raise ValueError(f"Synthetic currency mismatch for {observation.investor_name}.")
        has_override = investor.investor_name == "Cedar Pension Trust"
        selected_rule: InvestorRuleResult = override_rule if has_override else default_rule
        calculated_fee = _money(investor.commitment * rate)
        if observation.management_fee != calculated_fee:
            raise ValueError(
                f"Synthetic fee fixture is inconsistent for {observation.investor_name}."
            )
        if has_override and calculated_fee > observation.base_investment_contribution:
            raise ValueError("Management fee exceeds the base contribution; review is required.")

        expected_total = observation.base_investment_contribution
        expected_investment = observation.base_investment_contribution - calculated_fee
        rule_source: Literal["lpa", "side_letter"] = "side_letter"
        selected_rule_id = "RULE-SL-CEDAR-FEE"
        override_rule_id: str | None = selected_rule_id
        citations = [lpa_citation, side_letter_citation]
        if not has_override:
            expected_total += calculated_fee
            expected_investment = observation.base_investment_contribution
            rule_source = "lpa"
            selected_rule_id = "RULE-LPA-FEE"
            override_rule_id = None
            citations = [lpa_citation]

        expected_total = _money(expected_total)
        expected_investment = _money(expected_investment)
        variance = _money(observation.total_cash_payable - expected_total)
        status = ContractDecision.PASS if variance == 0 else ContractDecision.REVIEW_REQUIRED
        finding_code = (
            "CONTRACT_CALCULATION_PASS"
            if status == ContractDecision.PASS
            else "SIDE_LETTER_FEE_OVERRIDE_NOT_APPLIED"
        )
        calculations.append(
            FeeCallCalculation(
                investor_id=investor.investor_id,
                investor_name=investor.investor_name,
                status=status,
                currency=investor.currency,
                commitment=investor.commitment,
                quarterly_fee_rate=rate,
                calculated_management_fee=calculated_fee,
                base_investment_contribution=observation.base_investment_contribution,
                expected_investment_component=expected_investment,
                expected_fee_component=calculated_fee,
                expected_total_cash_payable=expected_total,
                observed_total_cash_payable=observation.total_cash_payable,
                variance=variance,
                rule_source=rule_source,
                finding_codes=[finding_code],
            )
        )
        resolved_rules.append(
            ResolvedContractRule(
                investor_id=investor.investor_id,
                investor_name=investor.investor_name,
                selected_rule_id=selected_rule_id,
                default_rule_id="RULE-LPA-FEE",
                override_rule_id=override_rule_id,
                resolution_reason=selected_rule.explanation,
                decision=status,
                citations=citations,
            )
        )
        if status == ContractDecision.PASS:
            findings.append(
                ContractFinding(
                    code=finding_code,
                    severity="pass",
                    title="Contract calculation passed",
                    detail=(
                        "The LPA default applies and the administrator total agrees with the "
                        "deterministic fee calculation."
                    ),
                    investor_name=investor.investor_name,
                    expected=f"GBP {expected_total:,.2f}",
                    observed=f"GBP {observation.total_cash_payable:,.2f}",
                    source_rule_ids=[selected_rule_id],
                )
            )
        else:
            findings.append(
                ContractFinding(
                    code=finding_code,
                    severity="high",
                    title="Side-letter fee override not applied",
                    detail=(
                        "The administrator used the LPA default treatment for an investor with "
                        "an active investor-specific override."
                    ),
                    investor_name=investor.investor_name,
                    expected=f"GBP {expected_total:,.2f}",
                    observed=f"GBP {observation.total_cash_payable:,.2f}",
                    source_rule_ids=["RULE-LPA-FEE", selected_rule_id],
                )
            )
            work_items.append(
                ContractWorkItem(
                    priority="high",
                    owner="Investor Operations",
                    title="Apply Cedar Pension Trust side-letter fee treatment",
                    instruction=(
                        "Recalculate the drawdown using the investor-specific side-letter rule "
                        "and obtain reviewer approval before investor reporting or call release."
                    ),
                    finding_code=finding_code,
                )
            )

    rules = [
        _rule_view(
            rule_id="RULE-LPA-FEE",
            title="LPA default management-fee treatment",
            scope="fund_default",
            value="0.50% quarterly on commitment; fee is additional to the contribution",
            effective_date=lpa.effective_date,
            explicit_override=False,
            source=lpa_citation,
        ),
        _rule_view(
            rule_id="RULE-SL-CEDAR-FEE",
            title="Cedar management-fee override",
            scope="investor_specific",
            investor_name="Cedar Pension Trust",
            value="fee reduces the contribution pound-for-pound and does not increase total cash",
            effective_date=side_letter.effective_date,
            explicit_override=True,
            source=side_letter_citation,
        ),
    ]
    manifest_hash = hashlib.sha256(
        "".join(
            _sha256(path) for path in (lpa_path, side_letter_path, investor_path, calculation_path)
        ).encode()
    ).hexdigest()
    return ContractDemoResponse(
        documents=repository.list_documents(),
        rules=rules,
        analysis=ContractAnalysis(
            decision=ContractDecision.REVIEW_REQUIRED,
            fund_name=DEMO_FUND_NAME,
            calculation_date=DEMO_CALCULATION_DATE,
            investor_count=len(calculations),
            non_standard_investor_count=1,
            rules_extracted=len(rules),
            rules_applied=len(resolved_rules),
            conflicts_open=0,
            potential_overcall=sum(
                (result.variance for result in calculations if result.variance > 0),
                start=Decimal("0.00"),
            ),
            findings=findings,
            resolved_rules=resolved_rules,
            calculation_results=calculations,
            work_items=work_items,
        ),
        evidence=ContractEvidence(
            document_sha256={
                lpa_path.name: _sha256(lpa_path),
                side_letter_path.name: _sha256(side_letter_path),
            },
            workbook_sha256={
                investor_path.name: _sha256(investor_path),
                calculation_path.name: _sha256(calculation_path),
            },
            fixture_manifest_sha256=manifest_hash,
        ),
    )
