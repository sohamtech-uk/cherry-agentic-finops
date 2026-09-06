from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_nav_canvas_exposes_document_upload_and_views() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "NAV close workbench" in html
    assert 'id="file-input"' in html
    assert 'multiple accept=".pdf,.xlsx,.xls,.csv,.json,.txt,.md,.zip' in html
    assert 'data-view="canvas"' in html
    assert 'data-view="document"' in html
    assert 'id="document-list"' in html
    assert 'id="asset-dock"' in html
    assert 'id="run-reconcile"' in html
    assert 'id="run-review"' in html
    assert 'id="open-decision"' in html


def test_nav_canvas_calls_governed_fund_manager_endpoints() -> None:
    script = (STATIC / "cfo_canvas.js").read_text(encoding="utf-8")
    assert "/api/fund-manager/cases" in script
    assert "/nav/readiness" in script
    assert "/nav/reconcile" in script
    assert "/nav/review" in script
    assert "/nav/decision" in script
    assert "FormData" in script
    assert "sessionStorage" in script


def test_nav_canvas_keeps_financial_boundary_visible() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "No official NAV or production ledger is amended" in html
    assert "A person still owns the sign-off decision" in html
