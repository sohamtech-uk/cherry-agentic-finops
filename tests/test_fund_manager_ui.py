from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


def test_nav_launcher_is_attached_to_the_review_plan_action_row() -> None:
    fund_manager_source = (STATIC_DIR / "fund_manager.js").read_text(encoding="utf-8")
    nav_source = (STATIC_DIR / "nav_quality_controller.js").read_text(encoding="utf-8")

    assert 'id="fm-workflow-tabs"' not in fund_manager_source
    assert 'const executeButton = stage.querySelector("#fm-execute")' in nav_source
    assert 'navButton.textContent = "NAV Quality Controller →"' in nav_source
    assert "actions.appendChild(navButton)" in nav_source
    assert 'document.querySelector("#fund-manager .fm-head")' not in nav_source
    assert 'document.querySelector("#fm-nav-launcher")' not in nav_source
