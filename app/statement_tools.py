"""Atomic deterministic primitives for the NAV Guardian Statement Review Agent.

Mirrors app/reconciliation_tools.py's approach for the Reconciliation Agent: intentionally
low-level building blocks -- read a document, locate a section or entity, diff two periods' text
or dates -- so the agent composes its own semantic review (has a subsequent event been moved to
the right section? is this disclosure stale?) instead of being handed one opaque verdict. Section
and entity location are mechanical text operations with heuristics that can miss real structure;
interpreting what a match means is left to the agent, and a "not found" result is evidence to
investigate further, not proof that a section or entity is absent from the document.

Reuses app.contracts.read_document_pages for PDF/TXT/Markdown extraction, exactly as the contract
ingestion pipeline does, so both agents are reading documents the same way.
"""

from __future__ import annotations

import difflib
import mimetypes
import re
from pathlib import Path
from typing import Any

from app.contracts import read_document_pages

_DATE_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)


def _read_file_text(document_path: str) -> str:
    path = Path(document_path)
    if not path.is_file():
        raise ValueError(f"Document path {document_path!r} does not exist.")
    content = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    pages = read_document_pages(content, mime_type, path.name)
    return "\n".join(text for _, text in pages)


def read_document(document_path: str) -> dict[str, Any]:
    """Extract a document's full text (PDF, TXT or Markdown), for ad hoc inspection.

    Args:
        document_path: Local path to the document.
    """

    text = _read_file_text(document_path)
    return {
        "document": Path(document_path).name,
        "character_count": len(text),
        "text": text,
    }


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80 or stripped.endswith((".", ",", ";")):
        return False
    words = stripped.split()
    return bool(words) and len(words) <= 12 and (stripped.isupper() or stripped.istitle())


def find_section(document_path: str, heading: str) -> dict[str, Any]:
    """Locate a named section by its heading and return the text from that heading up to the
    next heading-like line. This is a heuristic text search, not proof the section is absent if
    nothing is found — the heading may be phrased differently in this document.

    Args:
        document_path: Local path to the document.
        heading: Section heading to search for, e.g. "Subsequent Events".
    """

    lines = _read_file_text(document_path).splitlines()
    needle = heading.casefold()
    start = next((i for i, line in enumerate(lines) if needle in line.casefold()), None)
    if start is None:
        return {"document": Path(document_path).name, "heading": heading, "found": False}

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _looks_like_heading(lines[index]) and needle not in lines[index].casefold():
            end = index
            break

    return {
        "document": Path(document_path).name,
        "heading": heading,
        "found": True,
        "start_line": start + 1,
        "end_line": end,
        "text": "\n".join(lines[start:end]).strip(),
    }


def find_entity(document_path: str, entity_name: str, context_chars: int = 160) -> dict[str, Any]:
    """Find every mention of a named entity and return the surrounding text for each occurrence.

    Args:
        document_path: Local path to the document.
        entity_name: Entity to search for, e.g. a portfolio company or investor name.
        context_chars: Characters of surrounding context to include on each side of a match.
    """

    text = _read_file_text(document_path)
    matches = []
    for match in re.finditer(re.escape(entity_name), text, flags=re.IGNORECASE):
        start = max(0, match.start() - context_chars)
        end = min(len(text), match.end() + context_chars)
        matches.append({"offset": match.start(), "context": text[start:end].strip()})

    return {
        "document": Path(document_path).name,
        "entity": entity_name,
        "occurrences": len(matches),
        "matches": matches,
    }


def compare_periods(current_document_path: str, prior_document_path: str) -> dict[str, Any]:
    """Line-diff a current-period document against the prior period's, to surface exactly what
    changed (or, just as importantly, what stayed identical and may be a stale carry-forward).

    Args:
        current_document_path: Local path to the current-period document.
        prior_document_path: Local path to the prior-period document.
    """

    current_lines = _read_file_text(current_document_path).splitlines()
    prior_lines = _read_file_text(prior_document_path).splitlines()
    diff = list(
        difflib.unified_diff(
            prior_lines,
            current_lines,
            fromfile=Path(prior_document_path).name,
            tofile=Path(current_document_path).name,
            lineterm="",
        )
    )
    added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]

    return {
        "prior_document": Path(prior_document_path).name,
        "current_document": Path(current_document_path).name,
        "lines_added": added,
        "lines_removed": removed,
        "identical": not added and not removed,
        "diff": "\n".join(diff),
    }


def compare_dates(current_document_path: str, prior_document_path: str) -> dict[str, Any]:
    """Extract every date-like string from a current and a prior document and report which
    dates are new, which disappeared, and which are identical in both — an unchanged date is a
    candidate for a stale rolled-forward disclosure, not proof of one.

    Args:
        current_document_path: Local path to the current-period document.
        prior_document_path: Local path to the prior-period document.
    """

    current_text = _read_file_text(current_document_path)
    prior_text = _read_file_text(prior_document_path)
    current_dates = {match.group(0) for match in _DATE_PATTERN.finditer(current_text)}
    prior_dates = {match.group(0) for match in _DATE_PATTERN.finditer(prior_text)}

    return {
        "prior_document": Path(prior_document_path).name,
        "current_document": Path(current_document_path).name,
        "dates_only_in_current": sorted(current_dates - prior_dates),
        "dates_only_in_prior": sorted(prior_dates - current_dates),
        "dates_in_both": sorted(current_dates & prior_dates),
    }
