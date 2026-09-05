import json

from fastapi.testclient import TestClient

from app.api import app
from app.contracts import get_contract_repository

client = TestClient(app)


def seed_contract_api() -> None:
    client.post(
        "/api/contracts/documents",
        files={
            "files": (
                "fund-lpa.txt",
                b"Effective as of 1 January 2025\n"
                b"Section 4.2 Management Fees and Called Capital\n"
                b"Management fees shall not reduce or offset Called Capital unless a side "
                b"letter provides otherwise.",
                "text/plain",
            )
        },
        data={
            "document_type": "lpa",
            "fund_name": "Cedar Peak Growth Fund III LP",
        },
    )
    client.post(
        "/api/contracts/documents",
        files={
            "files": (
                "oakfield-side-letter.txt",
                b"Effective as of 1 March 2025\n"
                b"Section 4.2 Management Fee Offset\n"
                b"Notwithstanding Section 4.2, each management fee shall reduce, "
                b"pound-for-pound, Called Capital.",
                "text/plain",
            )
        },
        data={
            "document_type": "side_letter",
            "fund_name": "Cedar Peak Growth Fund III LP",
            "investor_name": "Oakfield Pension Trust",
        },
    )


def setup_function() -> None:
    get_contract_repository().clear()


def teardown_function() -> None:
    get_contract_repository().clear()


def test_contract_health_declares_tools_and_control_boundary() -> None:
    response = client.get("/api/contracts/health")

    assert response.status_code == 200
    body = response.json()
    assert body["tools"] == [
        "search_lpa",
        "search_side_letter",
        "extract_clause",
        "get_effective_date",
        "get_investor_rule",
    ]
    assert "deterministic code" in body["control_boundary"]


def test_contract_demo_finds_side_letter_nav_error() -> None:
    response = client.post("/api/contracts/demo/side-letter-fee")

    assert response.status_code == 200
    body = response.json()
    assert body["synthetic"] is True
    assert body["sponsor_native"] is False
    assert "No sponsor contract document was supplied" in body["message"]
    assert body["analysis"]["decision"] == "review_required"
    assert body["analysis"]["potential_overcall"] == "100000.00"
    results = {item["investor_name"]: item for item in body["analysis"]["calculation_results"]}
    assert results["Cedar Pension Trust"]["status"] == "review_required"
    assert results["Cedar Pension Trust"]["expected_total_cash_payable"] == "1000000.00"
    assert results["Cedar Pension Trust"]["variance"] == "100000.00"
    assert results["Orchard Institutional LP"]["status"] == "pass"
    assert results["Orchard Institutional LP"]["expected_total_cash_payable"] == "1100000.00"
    assert body["analysis"]["findings"][1]["code"] == ("SIDE_LETTER_FEE_OVERRIDE_NOT_APPLIED")
    assert all(rule["source"]["section_reference"] for rule in body["rules"])
    assert all(body["evidence"]["document_sha256"].values())
    assert get_contract_repository().list_documents() == []


def test_upload_search_and_extract_contract() -> None:
    upload = client.post(
        "/api/contracts/documents",
        files={
            "files": (
                "fund-lpa.txt",
                b"Effective as of 1 January 2025\nSection 4.2 Management Fee\n"
                b"The management fee is 1.5% per annum.",
                "text/plain",
            )
        },
        data={"document_type": "lpa", "fund_name": "Cedar Peak Fund"},
    )

    assert upload.status_code == 200
    document_id = upload.json()["documents"][0]["document_id"]
    search = client.post(
        "/api/contracts/search/lpa",
        json={"query": "management fee rate", "fund_name": "Cedar Peak Fund"},
    )
    clause = client.get(f"/api/contracts/documents/{document_id}/clauses/4.2")

    assert search.status_code == 200
    assert search.json()["hits"][0]["citation"]["document_id"] == document_id
    assert clause.status_code == 200
    assert "1.5%" in clause.json()["text"]


def test_nav_check_endpoint_returns_contract_citation() -> None:
    seed_contract_api()

    response = client.post(
        "/api/contracts/nav-checks/investor-capital",
        json={
            "investor_name": "Oakfield Pension Trust",
            "fund_name": "Cedar Peak Growth Fund III LP",
            "currency": "GBP",
            "gross_called_capital": 2_000_000,
            "management_fee": 125_000,
            "administrator_called_capital": 2_000_000,
            "as_of_date": "2026-06-30",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fail"
    assert body["variance"] == "125000.00"
    assert body["rule"]["citations"][0]["section_reference"] == "4.2"


def test_side_letter_upload_requires_investor_name() -> None:
    response = client.post(
        "/api/contracts/documents",
        files={"files": ("side-letter.txt", b"Section 1 Terms", "text/plain")},
        data={"document_type": "side_letter", "fund_name": "Cedar Peak Fund"},
    )

    assert response.status_code == 422
    assert "investor_name is required" in response.json()["detail"]


def test_nav_review_uses_source_backed_contract_rule() -> None:
    seed_contract_api()
    summary = json.dumps(
        {
            "legal_entity": "Cedar Peak Growth Fund III LP",
            "period_end": "2026-06-30",
            "currency": "GBP",
            "total_assets": 3_000_000,
            "total_liabilities": 0,
            "reported_equity": 3_000_000,
            "opening_nav": 3_000_000,
            "closing_nav": 3_000_000,
            "investor_capital": [
                {
                    "investor": "Oakfield Pension Trust",
                    "reported_capital": 3_000_000,
                    "management_fee": 125_000,
                }
            ],
        }
    ).encode()

    response = client.post(
        "/api/nav-quality/review",
        files={"nav_summary": ("nav-summary.json", summary, "application/json")},
        data={"use_contract_documents": "true"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_rule_source"] == "source_backed_contract_documents"
    assert body["review"]["action"] == "return_to_administrator"
    assert any(
        finding["code"] == "side_letter.rule_violation" for finding in body["review"]["findings"]
    )
    source = body["evidence"]["contract_sources"][0]
    assert source["document_id"].startswith("CTR-")
    assert source["section_reference"] == "4.2"
    assert len(source["source_sha256"]) == 64
    assert len(body["evidence"]["input_sha256"]["resolved_contract_rules"]) == 64
