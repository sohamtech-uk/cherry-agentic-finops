"""Synthetic judge fixtures for the isolated Cherry CFO cash-application slice."""

from __future__ import annotations

from typing import Any

from app.cash_application.eval_adapter import run_case


def clean_multi_invoice_demo() -> dict[str, Any]:
    """Run RCPT-1041 from fresh evidence through the deterministic simulated adapter."""

    task: dict[str, object] = {
        "as_of_date": "2026-09-05",
        "receipt": {
            "id": "RCPT-1041",
            "source_system": "SYNTHETIC_BANK",
            "source_transaction_id": "TX-1041",
            "amount": "12400.00",
            "currency": "GBP",
            "settlement_status": "BOOKED",
            "payer_name": "Northstar Retail Ltd",
            "reference": "REM-1041",
            "evidence_refs": ["bank:RCPT-1041"],
        },
        "customers": [
            {
                "id": "CUST-0042",
                "name": "Northstar Retail Ltd",
                "aliases": ["NORTHSTAR RETAIL"],
                "evidence_refs": ["erp:CUST-0042"],
            }
        ],
        "invoices": [
            {
                "id": "INV-2208",
                "customer_id": "CUST-0042",
                "balance": "10000.00",
                "currency": "GBP",
                "status": "OPEN",
                "evidence_refs": ["erp:INV-2208:v7"],
            },
            {
                "id": "INV-2214",
                "customer_id": "CUST-0042",
                "balance": "2400.00",
                "currency": "GBP",
                "status": "OPEN",
                "evidence_refs": ["erp:INV-2214:v4"],
            },
        ],
        "remittance": {
            "id": "REM-1041",
            "customer_id": "CUST-0042",
            "lines": [
                {"invoice_id": "INV-2208", "amount": "10000.00"},
                {"invoice_id": "INV-2214", "amount": "2400.00"},
            ],
            "evidence_refs": [
                "remit:REM-1041#line-1",
                "remit:REM-1041#line-2",
            ],
        },
        "policies": [],
        "prior_applications": [],
    }
    outcome = run_case(task, "DEMO-RCPT-1041-trial-1")
    return {
        "scenario": "clean_multi_invoice",
        "receipt_context": task["receipt"],
        "remittance": task["remittance"],
        "outcome": outcome,
        "boundary": "SIMULATED — no Cherry Money production write or payment initiation",
    }
