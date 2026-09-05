"""Fixture loading and validation for the cash-application eval suite."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

FIXTURE_DIR = Path(__file__).with_name("fixtures")
CORE_FIXTURES = FIXTURE_DIR / "core_cases.json"
HELD_OUT_FIXTURES = FIXTURE_DIR / "held_out_cases.json"

MONEY_KEYS = {
    "amount",
    "balance",
    "balance_after",
    "applied_amount",
    "unapplied_amount",
    "authority_limit",
    "max_auto_writeoff",
    "max_auto_amount",
    "proposed_max_auto_writeoff",
    "proposed_max_auto_amount",
}
REQUIRED_OUTCOME_KEYS = {
    "case_id",
    "receipt",
    "application",
    "applications",
    "invoices",
    "adjustments",
    "exception",
    "review",
    "policy",
    "audit_events",
    "trace",
    "review_packet",
}


@dataclass(frozen=True)
class EvalCase:
    """One eval task, including private grader expectations."""

    case_id: str
    title: str
    tags: tuple[str, ...]
    task: dict[str, Any]
    expected: dict[str, Any]

    @property
    def review_required(self) -> bool:
        return bool(self.expected["safety"]["review_required"])


def money(value: Any, *, location: str) -> Decimal:
    """Parse a canonical decimal string without accepting float ambiguity."""

    if not isinstance(value, str):
        raise ValueError(f"{location} must be a decimal string, got {type(value).__name__}")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{location} is not a valid decimal: {value!r}") from exc
    exponent = parsed.as_tuple().exponent
    if not parsed.is_finite() or not isinstance(exponent, int) or exponent < -2:
        raise ValueError(f"{location} must be finite with at most two decimal places")
    return parsed


def _validate_money_values(value: Any, location: str = "case") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_location = f"{location}.{key}"
            if key in MONEY_KEYS and nested is not None:
                money(nested, location=nested_location)
            else:
                _validate_money_values(nested, nested_location)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_money_values(nested, f"{location}[{index}]")


def validate_case(case: EvalCase) -> None:
    """Validate fixture structure without executing product behavior."""

    if not case.case_id or not case.title:
        raise ValueError("Every eval case needs a non-empty id and title")
    missing_expected = {"final", "audit", "trace", "safety"} - case.expected.keys()
    if missing_expected:
        raise ValueError(f"{case.case_id}: expected missing {sorted(missing_expected)}")
    missing_outcome = REQUIRED_OUTCOME_KEYS - case.expected["final"].keys()
    if missing_outcome:
        raise ValueError(f"{case.case_id}: final outcome missing {sorted(missing_outcome)}")
    if case.expected["final"]["case_id"] != case.case_id:
        raise ValueError(f"{case.case_id}: final case_id does not match fixture id")
    safety = case.expected["safety"]
    if set(safety) != {"review_required", "allowed_pre_review_applications"}:
        raise ValueError(f"{case.case_id}: safety contract has unexpected keys")
    _validate_money_values(case.task, case.case_id)
    _validate_money_values(case.expected, f"{case.case_id}.expected")


def _read_fixture(path: Path) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported schema version")
    cases = [
        EvalCase(
            case_id=item["id"],
            title=item["title"],
            tags=tuple(item.get("tags", [])),
            task=item["task"],
            expected=item["expected"],
        )
        for item in raw["cases"]
    ]
    for case in cases:
        validate_case(case)
    return cases


def load_cases(suite: str = "core") -> list[EvalCase]:
    """Load core, held-out, or all fixture cases with duplicate-id checks."""

    paths = {
        "core": [CORE_FIXTURES],
        "held-out": [HELD_OUT_FIXTURES],
        "all": [CORE_FIXTURES, HELD_OUT_FIXTURES],
    }
    try:
        selected = paths[suite]
    except KeyError as exc:
        raise ValueError(f"Unknown suite {suite!r}; expected one of {sorted(paths)}") from exc
    cases = [case for path in selected for case in _read_fixture(path)]
    ids = [case.case_id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate eval case ids: {duplicates}")
    return cases


def public_task(case: EvalCase) -> dict[str, Any]:
    """Return only data an implementation may see, never grader expectations."""

    return cast(dict[str, Any], json.loads(json.dumps(case.task)))
