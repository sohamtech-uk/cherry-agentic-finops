import json

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.private_markets_io import parse_cash_json

client = TestClient(app)


def test_parse_cash_json_accepts_object_shape_and_aliases() -> None:
    payload = {
        "transactions": [
            {
                "id": "TXN-JSON-1",
                "date": "2026-09-05",
                "amount_gbp": 1249500,
                "currency": "GBP",
                "name": "Oakfield Pension Trust",
                "payment_reference": "NCGFIII-CALL-2026-03 / LP-001",
                "narrative": "Capital contribution",
            }
        ]
    }

    transactions = parse_cash_json(json.dumps(payload).encode())

    assert len(transactions) == 1
    transaction = transactions[0]
    assert transaction.transaction_id == "TXN-JSON-1"
    assert transaction.direction == "credit"
    assert transaction.amount == 1_249_500
    assert transaction.reference == "NCGFIII-CALL-2026-03 / LP-001"


def test_parse_cash_json_infers_negative_amount_as_debit() -> None:
    transactions = parse_cash_json(
        b'[{"transaction_id":"TXN-2","booking_date":"2026-09-05","amount":-25,"currency":"GBP"}]'
    )

    assert transactions[0].direction == "debit"
    assert transactions[0].amount == 25


def test_parse_cash_json_rejects_missing_date() -> None:
    with pytest.raises(ValueError, match="missing booking_date/date"):
        parse_cash_json(b'[{"transaction_id":"TXN-3","amount":100}]')


def test_integrated_health_declares_pdf_excel_json_contract() -> None:
    response = client.get("/api/private-markets/integration/health")

    assert response.status_code == 200
    body = response.json()
    assert body["input_contract"] == ["pdf", "excel", "json"]
    assert body["input_required"] == {"pdf": True, "excel": True, "json": False}
    assert body["input_multiplicity"]["json"] == "zero_or_one"
    assert "fundops_studio_configured" in body


def test_integrated_openapi_marks_cash_json_optional() -> None:
    spec = client.get("/openapi.json").json()
    request_schema = spec["paths"]["/api/private-markets/analyse-integrated"]["post"][
        "requestBody"
    ]["content"]["multipart/form-data"]["schema"]
    if "$ref" in request_schema:
        component_name = request_schema["$ref"].rsplit("/", 1)[-1]
        request_schema = spec["components"]["schemas"][component_name]

    assert "capital_call" in request_schema["required"]
    assert "commitments" in request_schema["required"]
    assert "fund_json" not in request_schema["required"]
