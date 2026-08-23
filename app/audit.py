from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.models import AuditEvent, utc_now

GENESIS_HASH = "0" * 64


def _canonical_payload(
    *,
    sequence: int,
    occurred_at: datetime,
    actor: str,
    action: str,
    details: dict[str, Any],
    previous_hash: str,
) -> bytes:
    payload = {
        "sequence": sequence,
        "occurred_at": occurred_at.isoformat(),
        "actor": actor,
        "action": action,
        "details": details,
        "previous_hash": previous_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def append_event(
    events: list[AuditEvent],
    *,
    actor: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    occurred_at = utc_now()
    sequence = len(events) + 1
    previous_hash = events[-1].event_hash if events else GENESIS_HASH
    details = details or {}
    event_hash = hashlib.sha256(
        _canonical_payload(
            sequence=sequence,
            occurred_at=occurred_at,
            actor=actor,
            action=action,
            details=details,
            previous_hash=previous_hash,
        )
    ).hexdigest()
    event = AuditEvent(
        sequence=sequence,
        occurred_at=occurred_at,
        actor=actor,
        action=action,
        details=details,
        previous_hash=previous_hash,
        event_hash=event_hash,
    )
    events.append(event)
    return event


def verify_chain(events: list[AuditEvent]) -> bool:
    previous_hash = GENESIS_HASH
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence or event.previous_hash != previous_hash:
            return False
        calculated = hashlib.sha256(
            _canonical_payload(
                sequence=event.sequence,
                occurred_at=event.occurred_at,
                actor=event.actor,
                action=event.action,
                details=event.details,
                previous_hash=event.previous_hash,
            )
        ).hexdigest()
        if calculated != event.event_hash:
            return False
        previous_hash = event.event_hash
    return True
