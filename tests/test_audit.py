from app.audit import append_event, verify_chain


def test_audit_chain_detects_tampering() -> None:
    events = []
    append_event(events, actor="agent", action="first", details={"amount": "10.00"})
    append_event(events, actor="human", action="approved", details={"name": "Reviewer"})
    assert verify_chain(events)

    events[0].details["amount"] = "999.00"
    assert not verify_chain(events)
