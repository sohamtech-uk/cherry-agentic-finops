from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader

TWOPLACES = Decimal("0.01")
SECTION_HEADING = re.compile(
    r"^(?:#{1,6}\s*)?(?:(?:section|article)\s+)?"
    r"(?P<section>(?:\d+(?:\.\d+)*)|(?:[IVXLCDM]+))"
    r"[\s.():\-–—]+(?P<title>[^\n]{2,160})$",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "shall",
    "that",
    "the",
    "this",
    "to",
    "with",
}


class ContractDocumentType(StrEnum):
    LPA = "lpa"
    SIDE_LETTER = "side_letter"


class RuleStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    REVIEW_REQUIRED = "review_required"


class NAVCheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW_REQUIRED = "review_required"


class ContractClause(BaseModel):
    clause_id: str
    document_id: str
    section_reference: str
    heading: str | None = None
    page_number: int = Field(ge=1)
    text: str


class ContractDocument(BaseModel):
    document_id: str
    document_type: ContractDocumentType
    file_name: str
    fund_name: str
    investor_name: str | None = None
    effective_date: date | None = None
    effective_date_source: str | None = None
    sha256: str
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    clauses: list[ContractClause] = Field(default_factory=list)


class ContractDocumentSummary(BaseModel):
    document_id: str
    document_type: ContractDocumentType
    file_name: str
    fund_name: str
    investor_name: str | None = None
    effective_date: date | None = None
    sha256: str
    clause_count: int


class ContractCitation(BaseModel):
    document_id: str
    file_name: str
    document_type: ContractDocumentType
    section_reference: str
    page_number: int
    quote: str
    extraction_confidence: int = Field(default=100, ge=0, le=100)


class ContractSearchHit(BaseModel):
    score: int = Field(ge=0, le=100)
    citation: ContractCitation
    heading: str | None = None
    fund_name: str
    investor_name: str | None = None
    effective_date: date | None = None


class ContractSearchResult(BaseModel):
    query: str
    document_type: ContractDocumentType
    total: int
    hits: list[ContractSearchHit]


class ClauseExtractionResult(BaseModel):
    document_id: str
    file_name: str
    section_reference: str
    heading: str | None = None
    text: str
    page_numbers: list[int]
    truncated: bool = False
    citation: ContractCitation


class EffectiveDateResult(BaseModel):
    document_id: str
    file_name: str
    effective_date: date | None = None
    status: Literal["found", "not_found"]
    source_text: str | None = None
    citation: ContractCitation | None = None


class InvestorRuleResult(BaseModel):
    investor_name: str
    rule_name: str
    status: RuleStatus
    value: bool | str | None = None
    effective_date: date | None = None
    source_precedence: ContractDocumentType | None = None
    requires_review: bool
    explanation: str
    citations: list[ContractCitation] = Field(default_factory=list)


class InvestorCapitalCheck(BaseModel):
    investor_name: str
    fund_name: str
    currency: str = "GBP"
    gross_called_capital: Decimal
    management_fee: Decimal
    administrator_called_capital: Decimal
    as_of_date: date | None = None

    @field_validator(
        "gross_called_capital",
        "management_fee",
        "administrator_called_capital",
        mode="before",
    )
    @classmethod
    def normalise_money(cls, value: object) -> Decimal:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    @field_validator("currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        return value.strip().upper()


class InvestorCapitalCheckResult(BaseModel):
    status: NAVCheckStatus
    investor_name: str
    currency: str
    gross_called_capital: Decimal
    management_fee: Decimal
    expected_called_capital: Decimal | None = None
    administrator_called_capital: Decimal
    variance: Decimal | None = None
    rule: InvestorRuleResult
    explanation: str


class ContractDocumentNotFound(KeyError):
    pass


class ContractClauseNotFound(KeyError):
    pass


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN_PATTERN.findall(value.casefold()) if token not in STOP_WORDS}


def _normalise_section(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold().replace("section", ""))


def _parse_date(value: str) -> date | None:
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;")
    for pattern in (
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    return None


def _find_effective_date(pages: list[tuple[int, str]]) -> tuple[date | None, str | None]:
    date_value = (
        r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{4}|"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}|"
        r"\d{1,2}/\d{1,2}/\d{4})"
    )
    patterns = [
        re.compile(
            rf"(?:effective(?:\s+date)?|effective\s+as\s+of|dated\s+as\s+of)\s*[:,-]?\s*({date_value})",
            re.IGNORECASE,
        ),
        re.compile(rf"\bdate\s*:\s*({date_value})", re.IGNORECASE),
    ]
    for _, text in pages:
        for pattern in patterns:
            match = pattern.search(text)
            if match and (parsed := _parse_date(match.group(1))):
                start = max(0, match.start() - 60)
                end = min(len(text), match.end() + 60)
                return parsed, re.sub(r"\s+", " ", text[start:end]).strip()
    return None, None


def read_document_pages(content: bytes, mime_type: str, file_name: str) -> list[tuple[int, str]]:
    """Extract a document's text as (page_number, text) tuples. Shared by contract ingestion and
    the statement-review tools; supports PDF, TXT and Markdown."""

    if not content:
        raise ValueError(f"Document {file_name!r} is empty.")
    is_pdf = mime_type == "application/pdf" or file_name.casefold().endswith(".pdf")
    if is_pdf:
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [
                (index, page.extract_text() or "") for index, page in enumerate(reader.pages, 1)
            ]
        except Exception as exc:
            raise ValueError(f"The PDF {file_name!r} could not be read.") from exc
        if not any(text.strip() for _, text in pages):
            raise ValueError(f"PDF {file_name!r} contains no extractable text; OCR is required.")
        return pages
    if mime_type.startswith("text/") or file_name.casefold().endswith((".txt", ".md")):
        try:
            return [(1, content.decode("utf-8-sig"))]
        except UnicodeDecodeError as exc:
            raise ValueError(f"Text document {file_name!r} must use UTF-8 encoding.") from exc
    raise ValueError(f"Document {file_name!r} must be PDF, TXT or Markdown.")


def _split_clauses(document_id: str, pages: list[tuple[int, str]]) -> list[ContractClause]:
    clauses: list[ContractClause] = []
    sequence = 0
    for page_number, page_text in pages:
        current_section = f"page-{page_number}"
        current_heading: str | None = None
        current_lines: list[str] = []

        def flush(section_reference: str, heading: str | None, page: int) -> None:
            nonlocal sequence, current_lines
            text = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
            if not text:
                current_lines = []
                return
            for start in range(0, len(text), 3500):
                sequence += 1
                clauses.append(
                    ContractClause(
                        clause_id=f"{document_id}-C{sequence:04d}",
                        document_id=document_id,
                        section_reference=section_reference,
                        heading=heading,
                        page_number=page,
                        text=text[start : start + 3500],
                    )
                )
            current_lines = []

        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading_match = SECTION_HEADING.match(line)
            if heading_match:
                flush(current_section, current_heading, page_number)
                current_section = heading_match.group("section")
                current_heading = heading_match.group("title").strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        flush(current_section, current_heading, page_number)
    return clauses


def _excerpt(text: str, query: str, limit: int = 480) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    positions = [compact.casefold().find(token) for token in _tokens(query)]
    positions = [position for position in positions if position >= 0]
    centre = min(positions) if positions else 0
    start = max(0, centre - limit // 3)
    end = min(len(compact), start + limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end].strip()}{suffix}"


RULE_QUERIES = {
    "management_fee_offsets_called_capital": "management fee offset reduce called capital",
    "management_fee_rate": "management fee rate percentage",
    "expense_allocation": "fund expenses allocation management company portfolio company",
    "reporting_frequency": "investor reporting frequency quarterly monthly annual",
    "carry_rate": "carried interest carry percentage",
    "mfn": "most favoured nation most favored nation election",
    "excuse_right": "investor excuse exclusion investment right",
}


def _parse_rule_value(rule_name: str, text: str) -> bool | str | None:
    compact = re.sub(r"\s+", " ", text).casefold()
    if rule_name == "management_fee_offsets_called_capital":
        negative = [
            r"management fees?.{0,180}(?:shall not|does not|will not).{0,80}"
            r"(?:offset|reduce|deduct|count against).{0,100}called capital",
            r"called capital.{0,180}(?:shall not|is not).{0,80}"
            r"(?:reduced|offset).{0,100}management fees?",
        ]
        positive = [
            r"management fees?.{0,180}(?:offset|reduce|deduct|count(?:s|ed)? against)"
            r".{0,100}called capital",
            r"called capital.{0,180}(?:net of|reduced by|less).{0,100}management fees?",
        ]
        if any(re.search(pattern, compact) for pattern in negative):
            return False
        if any(re.search(pattern, compact) for pattern in positive):
            return True
        return None
    if rule_name in {"management_fee_rate", "carry_rate"}:
        label = "management fee" if rule_name == "management_fee_rate" else "carried interest|carry"
        match = re.search(rf"(?:{label}).{{0,100}}?(\d+(?:\.\d+)?)\s*(?:%|per cent)", compact)
        return f"{match.group(1)}%" if match else None
    if rule_name == "reporting_frequency":
        match = re.search(
            r"\b(monthly|quarterly|semi-annual|semi-annually|annual|annually)\b", compact
        )
        return match.group(1) if match else None
    if rule_name in {"mfn", "excuse_right"}:
        keywords = (
            ("most favoured nation", "most favored nation")
            if rule_name == "mfn"
            else ("excuse right", "excluded from", "excused from")
        )
        return True if any(keyword in compact for keyword in keywords) else None
    return None


def _has_explicit_override(text: str) -> bool:
    compact = re.sub(r"\s+", " ", text).casefold()
    return any(
        phrase in compact
        for phrase in (
            "notwithstanding",
            "shall instead",
            "shall be included within",
            "shall reduce pound-for-pound",
            "shall reduce, pound-for-pound",
            "in lieu of",
        )
    )


class ContractRepository:
    def __init__(self) -> None:
        self._documents: dict[str, ContractDocument] = {}
        self._lock = RLock()

    def clear(self) -> int:
        with self._lock:
            count = len(self._documents)
            self._documents.clear()
            return count

    def ingest(
        self,
        *,
        content: bytes,
        mime_type: str,
        file_name: str,
        document_type: ContractDocumentType,
        fund_name: str,
        investor_name: str | None = None,
        effective_date: date | None = None,
    ) -> ContractDocument:
        if document_type == ContractDocumentType.SIDE_LETTER and not investor_name:
            raise ValueError("investor_name is required for a side letter.")
        safe_file_name = Path(file_name).name.strip()
        if not safe_file_name or safe_file_name in {".", ".."}:
            raise ValueError("Contract file name is invalid.")
        content_hash = hashlib.sha256(content).hexdigest()
        identity = "|".join(
            [
                content_hash,
                document_type.value,
                fund_name.casefold(),
                (investor_name or "").casefold(),
            ]
        )
        document_id = f"CTR-{hashlib.sha256(identity.encode()).hexdigest()[:12].upper()}"
        pages = read_document_pages(content, mime_type, safe_file_name)
        detected_date, date_source = _find_effective_date(pages)
        clauses = _split_clauses(document_id, pages)
        document = ContractDocument(
            document_id=document_id,
            document_type=document_type,
            file_name=safe_file_name,
            fund_name=fund_name.strip(),
            investor_name=investor_name.strip() if investor_name else None,
            effective_date=effective_date or detected_date,
            effective_date_source=("Provided during ingestion" if effective_date else date_source),
            sha256=content_hash,
            clauses=clauses,
        )
        with self._lock:
            self._documents[document_id] = document
        return document.model_copy(deep=True)

    def list_documents(self) -> list[ContractDocumentSummary]:
        with self._lock:
            documents = [document.model_copy(deep=True) for document in self._documents.values()]
        return [
            ContractDocumentSummary(
                document_id=document.document_id,
                document_type=document.document_type,
                file_name=document.file_name,
                fund_name=document.fund_name,
                investor_name=document.investor_name,
                effective_date=document.effective_date,
                sha256=document.sha256,
                clause_count=len(document.clauses),
            )
            for document in sorted(documents, key=lambda item: item.ingested_at)
        ]

    def get(self, document_id: str) -> ContractDocument:
        with self._lock:
            document = self._documents.get(document_id)
            if document is None:
                raise ContractDocumentNotFound(document_id)
            return document.model_copy(deep=True)

    def search(
        self,
        *,
        query: str,
        document_type: ContractDocumentType,
        fund_name: str | None = None,
        investor_name: str | None = None,
        limit: int = 5,
    ) -> ContractSearchResult:
        query_tokens = _tokens(query)
        if not query_tokens:
            raise ValueError("Search query must contain a meaningful term.")
        with self._lock:
            documents = [document.model_copy(deep=True) for document in self._documents.values()]
        hits: list[ContractSearchHit] = []
        query_normalised = re.sub(r"\s+", " ", query).casefold().strip()
        for document in documents:
            if document.document_type != document_type:
                continue
            if fund_name and document.fund_name.casefold() != fund_name.casefold():
                continue
            if (
                investor_name
                and (document.investor_name or "").casefold() != investor_name.casefold()
            ):
                continue
            for clause in document.clauses:
                clause_tokens = _tokens(f"{clause.heading or ''} {clause.text}")
                overlap = len(query_tokens & clause_tokens) / len(query_tokens)
                phrase_bonus = 0.2 if query_normalised in clause.text.casefold() else 0
                heading_bonus = 0.08 if query_tokens & _tokens(clause.heading or "") else 0
                score = min(100, round((overlap * 0.72 + phrase_bonus + heading_bonus) * 100))
                if score <= 0:
                    continue
                hits.append(
                    ContractSearchHit(
                        score=score,
                        citation=ContractCitation(
                            document_id=document.document_id,
                            file_name=document.file_name,
                            document_type=document.document_type,
                            section_reference=clause.section_reference,
                            page_number=clause.page_number,
                            quote=_excerpt(clause.text, query),
                        ),
                        heading=clause.heading,
                        fund_name=document.fund_name,
                        investor_name=document.investor_name,
                        effective_date=document.effective_date,
                    )
                )
        hits.sort(key=lambda hit: (-hit.score, hit.citation.file_name, hit.citation.page_number))
        selected = hits[: max(1, min(limit, 20))]
        return ContractSearchResult(
            query=query,
            document_type=document_type,
            total=len(hits),
            hits=selected,
        )

    def extract_clause(self, document_id: str, section_reference: str) -> ClauseExtractionResult:
        document = self.get(document_id)
        target = _normalise_section(section_reference)
        matches = [
            clause
            for clause in document.clauses
            if _normalise_section(clause.section_reference) == target
            or (clause.heading and target in _normalise_section(clause.heading))
        ]
        if not matches:
            raise ContractClauseNotFound(f"{document_id}:{section_reference}")
        full_text = " ".join(clause.text for clause in matches)
        truncated = len(full_text) > 12_000
        text = full_text[:12_000]
        first = matches[0]
        citation = ContractCitation(
            document_id=document.document_id,
            file_name=document.file_name,
            document_type=document.document_type,
            section_reference=first.section_reference,
            page_number=first.page_number,
            quote=_excerpt(text, first.heading or section_reference),
        )
        return ClauseExtractionResult(
            document_id=document.document_id,
            file_name=document.file_name,
            section_reference=first.section_reference,
            heading=first.heading,
            text=text,
            page_numbers=sorted({clause.page_number for clause in matches}),
            truncated=truncated,
            citation=citation,
        )

    def get_effective_date(self, document_id: str) -> EffectiveDateResult:
        document = self.get(document_id)
        citation: ContractCitation | None = None
        if document.effective_date:
            source_clause = next(
                (
                    clause
                    for clause in document.clauses
                    if document.effective_date_source
                    and any(token in clause.text.casefold() for token in ("effective", "dated"))
                ),
                document.clauses[0] if document.clauses else None,
            )
            if source_clause:
                citation = ContractCitation(
                    document_id=document.document_id,
                    file_name=document.file_name,
                    document_type=document.document_type,
                    section_reference=source_clause.section_reference,
                    page_number=source_clause.page_number,
                    quote=document.effective_date_source or _excerpt(source_clause.text, "date"),
                )
        return EffectiveDateResult(
            document_id=document.document_id,
            file_name=document.file_name,
            effective_date=document.effective_date,
            status="found" if document.effective_date else "not_found",
            source_text=document.effective_date_source,
            citation=citation,
        )

    def get_investor_rule(
        self,
        *,
        investor_name: str,
        rule_name: str,
        as_of_date: date | None = None,
        fund_name: str | None = None,
    ) -> InvestorRuleResult:
        query = RULE_QUERIES.get(rule_name)
        if query is None:
            supported = ", ".join(sorted(RULE_QUERIES))
            raise ValueError(f"Unsupported rule_name. Choose one of: {supported}.")
        side_hits = self.search(
            query=query,
            document_type=ContractDocumentType.SIDE_LETTER,
            fund_name=fund_name,
            investor_name=investor_name,
            limit=20,
        ).hits
        lpa_hits = self.search(
            query=query,
            document_type=ContractDocumentType.LPA,
            fund_name=fund_name,
            limit=20,
        ).hits

        def active(hits: list[ContractSearchHit]) -> list[ContractSearchHit]:
            return [
                hit
                for hit in hits
                if as_of_date is None
                or hit.effective_date is None
                or hit.effective_date <= as_of_date
            ]

        active_side = active(side_hits)
        active_lpa = active(lpa_hits)
        source_hits = active_side or active_lpa
        precedence = ContractDocumentType.SIDE_LETTER if active_side else ContractDocumentType.LPA
        if not source_hits:
            return InvestorRuleResult(
                investor_name=investor_name,
                rule_name=rule_name,
                status=RuleStatus.NOT_FOUND,
                requires_review=True,
                explanation="No active LPA or investor side-letter clause supports this rule.",
            )

        undated_hits = [hit for hit in source_hits if hit.effective_date is None]
        if undated_hits:
            return InvestorRuleResult(
                investor_name=investor_name,
                rule_name=rule_name,
                status=RuleStatus.REVIEW_REQUIRED,
                source_precedence=precedence,
                requires_review=True,
                explanation=(
                    "A relevant contract term has no effective date, so precedence for the "
                    "reporting period cannot be determined safely."
                ),
                citations=[hit.citation for hit in undated_hits[:3]],
            )

        latest_date = max(hit.effective_date for hit in source_hits if hit.effective_date)
        latest_hits = [hit for hit in source_hits if hit.effective_date == latest_date]

        parsed = [
            (hit, value)
            for hit in latest_hits
            if (value := _parse_rule_value(rule_name, hit.citation.quote)) is not None
        ]
        if not parsed:
            return InvestorRuleResult(
                investor_name=investor_name,
                rule_name=rule_name,
                status=RuleStatus.REVIEW_REQUIRED,
                effective_date=latest_date,
                source_precedence=precedence,
                requires_review=True,
                explanation=(
                    "Relevant contractual text was found, but it could not be converted into a "
                    "deterministic rule. A reviewer must interpret the cited clause."
                ),
                citations=[hit.citation for hit in latest_hits[:3]],
            )

        if precedence == ContractDocumentType.SIDE_LETTER and not any(
            _has_explicit_override(hit.citation.quote) for hit, _ in parsed
        ):
            return InvestorRuleResult(
                investor_name=investor_name,
                rule_name=rule_name,
                status=RuleStatus.REVIEW_REQUIRED,
                effective_date=latest_date,
                source_precedence=precedence,
                requires_review=True,
                explanation=(
                    "The side letter mentions the rule but does not contain explicit override "
                    "language, so it cannot replace the LPA default automatically."
                ),
                citations=[hit.citation for hit, _ in parsed],
            )

        values = {str(value) for _, value in parsed}
        citations = [hit.citation for hit, _ in parsed]
        if len(values) > 1:
            return InvestorRuleResult(
                investor_name=investor_name,
                rule_name=rule_name,
                status=RuleStatus.CONFLICT,
                effective_date=latest_date,
                source_precedence=precedence,
                requires_review=True,
                explanation="Active clauses at the same precedence and effective date conflict.",
                citations=citations,
            )

        selected_hit, value = parsed[0]
        explanation = (
            "The active investor-specific side letter overrides the fund-level LPA term."
            if precedence == ContractDocumentType.SIDE_LETTER
            else "No active investor-specific override was found; the fund-level LPA term applies."
        )
        return InvestorRuleResult(
            investor_name=investor_name,
            rule_name=rule_name,
            status=RuleStatus.FOUND,
            value=value,
            effective_date=selected_hit.effective_date,
            source_precedence=precedence,
            requires_review=selected_hit.effective_date is None,
            explanation=explanation,
            citations=citations,
        )

    def check_investor_capital(self, check: InvestorCapitalCheck) -> InvestorCapitalCheckResult:
        rule = self.get_investor_rule(
            investor_name=check.investor_name,
            rule_name="management_fee_offsets_called_capital",
            as_of_date=check.as_of_date,
            fund_name=check.fund_name,
        )
        if rule.status != RuleStatus.FOUND or not isinstance(rule.value, bool):
            return InvestorCapitalCheckResult(
                status=NAVCheckStatus.REVIEW_REQUIRED,
                investor_name=check.investor_name,
                currency=check.currency,
                gross_called_capital=check.gross_called_capital,
                management_fee=check.management_fee,
                administrator_called_capital=check.administrator_called_capital,
                rule=rule,
                explanation=(
                    "The called-capital calculation was not evaluated because no unambiguous "
                    "effective contract rule is available."
                ),
            )
        if rule.value and check.management_fee > check.gross_called_capital:
            return InvestorCapitalCheckResult(
                status=NAVCheckStatus.REVIEW_REQUIRED,
                investor_name=check.investor_name,
                currency=check.currency,
                gross_called_capital=check.gross_called_capital,
                management_fee=check.management_fee,
                administrator_called_capital=check.administrator_called_capital,
                rule=rule,
                explanation=(
                    "The management fee exceeds called capital. The contract does not define "
                    "a safe negative-contribution treatment, so a reviewer must decide."
                ),
            )
        expected = check.gross_called_capital
        if rule.value:
            expected -= check.management_fee
        expected = expected.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        variance = (check.administrator_called_capital - expected).quantize(
            TWOPLACES, rounding=ROUND_HALF_UP
        )
        status = NAVCheckStatus.PASS if variance == 0 else NAVCheckStatus.FAIL
        return InvestorCapitalCheckResult(
            status=status,
            investor_name=check.investor_name,
            currency=check.currency,
            gross_called_capital=check.gross_called_capital,
            management_fee=check.management_fee,
            expected_called_capital=expected,
            administrator_called_capital=check.administrator_called_capital,
            variance=variance,
            rule=rule,
            explanation=(
                "Administrator called capital agrees with the effective contractual rule."
                if status == NAVCheckStatus.PASS
                else (
                    f"Administrator called capital differs from the contract-derived amount by "
                    f"{variance} {check.currency}."
                )
            ),
        )


_repository = ContractRepository()


def get_contract_repository() -> ContractRepository:
    return _repository
