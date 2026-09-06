from pathlib import Path


def test_analysis_theatre_replaces_generic_spinner_with_control_room() -> None:
    script = Path("app/static/fund_manager_completion.js").read_text(encoding="utf-8")
    css = Path("app/static/analysis_loading.css").read_text(encoding="utf-8")

    assert "Evidence Control Room" in script
    assert "ANALYSIS REQUEST IN FLIGHT" in script
    assert "Sequence · not fake progress" in script
    assert "No silent guesses." in script
    assert "Financial writes" in script
    assert "Payment authority" in script
    assert "Final decision" in script
    assert "window.loading = function enhancedLoading" in script
    assert "collectEvidence" in script
    assert "analysis_loading.css" in script

    assert ".loading.analysis-loading" in css
    assert ".analysis-core-wrap" in css
    assert ".analysis-path" in css
    assert "prefers-reduced-motion" in css


def test_analysis_theatre_keeps_truthful_synchronous_progress_copy() -> None:
    script = Path("app/static/fund_manager_completion.js").read_text(encoding="utf-8")

    assert "no intermediate completion is fabricated in the browser" in script
    assert "without inventing a percentage" in script
    assert "The API returns the completed result as one response" in script
