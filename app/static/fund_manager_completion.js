(() => {
  "use strict";

  const REPORT_MARKER = "data-fm-final-report";

  function addReportLink(container, before, caseId, format, label, primary = false) {
    if (container.querySelector(`[${REPORT_MARKER}="${format}"]`)) return;
    const link = document.createElement("a");
    link.className = `fm-button ${primary ? "primary" : "secondary"}`;
    link.href = `/api/fund-manager/cases/${encodeURIComponent(caseId)}/report.${format}`;
    link.setAttribute("download", "");
    link.setAttribute(REPORT_MARKER, format);
    link.textContent = label;
    container.insertBefore(link, before);
  }

  function enhanceCompletedDecision() {
    const stage = document.querySelector("#fm-stage");
    const caseData = typeof window.getFundManagerCase === "function"
      ? window.getFundManagerCase()
      : null;
    if (!stage || caseData?.stage !== "decided" || !caseData.case_id) return;

    // A recorded decision is the terminal state. Do not navigate back into earlier mutable stages.
    stage.querySelector("#fm-back")?.remove();

    const actions = stage.querySelector(".fm-stage-nav");
    if (!actions) return;
    const newCaseButton = actions.querySelector("#fm-new-case");

    addReportLink(
      actions,
      newCaseButton,
      caseData.case_id,
      "pdf",
      "Download PDF report ↓",
      true,
    );
    addReportLink(
      actions,
      newCaseButton,
      caseData.case_id,
      "xlsx",
      "Download Excel report ↓",
    );
  }

  function init() {
    enhanceCompletedDecision();
    const stage = document.querySelector("#fm-stage");
    if (stage) {
      const observer = new MutationObserver(enhanceCompletedDecision);
      observer.observe(stage, { childList: true, subtree: true });
    }
    window.addEventListener("fund-manager-case-updated", () => {
      window.setTimeout(enhanceCompletedDecision, 0);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
