(() => {
  "use strict";

  const REPORT_MARKER = "data-fm-final-report";
  const ANALYSIS_STYLE = "/static/analysis_loading.css";

  const PRINCIPLES = [
    {
      title: "No silent guesses.",
      body: "Ambiguous evidence stays visible for review instead of being quietly promoted to financial truth.",
    },
    {
      title: "AI reads. Rules decide.",
      body: "AI can help interpret and route evidence; deterministic controls own arithmetic and control outcomes.",
    },
    {
      title: "Every break has a trail.",
      body: "The useful output is not a chatbot answer. It is a finding with the source context needed to investigate it.",
    },
    {
      title: "Humans keep authority.",
      body: "Cherry can prepare and recommend. NAV approval, exception acceptance and payment authority stay with people.",
    },
  ];

  const NARRATIVES = [
    "Fund operations does not need another chatbot. It needs evidence-linked controls.",
    "Cherry separates document interpretation from deterministic financial arithmetic.",
    "Exceptions are surfaced for owned follow-up instead of being silently normalised away.",
    "Evidence lineage makes the answer reviewable after the demo, not just impressive during it.",
    "The final boundary is explicit: agents prepare the review; a fund manager makes the decision.",
  ];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

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

  function humanSize(bytes) {
    const value = Number(bytes || 0);
    if (!value) return "Selected evidence";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function fileType(name, detectedType = "") {
    if (detectedType) {
      const labels = {
        nav_summary: "NAV",
        nav_workbook: "NAV",
        investor_gl: "GL",
        side_letter_rules: "RULE",
        side_letter: "SIDE",
        lpa: "LPA",
        capital_call_notice: "CALL",
        bank_statement: "BANK",
        financial_statement: "FS",
      };
      if (labels[detectedType]) return labels[detectedType];
    }
    const extension = String(name || "").split(".").pop().toUpperCase();
    return extension && extension.length <= 5 ? extension : "FILE";
  }

  function collectEvidence() {
    const evidence = [];
    const seen = new Set();
    const add = (name, type, meta) => {
      if (!name) return;
      const key = `${name}:${meta}`;
      if (seen.has(key)) return;
      seen.add(key);
      evidence.push({ name, type: type || fileType(name), meta: meta || "Evidence" });
    };

    [
      "#capital-call-input",
      "#commitments-input",
      "#cash-input",
      "#fm-file-input",
      "#navqc-new-evidence",
    ].forEach((selector) => {
      const input = document.querySelector(selector);
      [...(input?.files || [])].forEach((file) => {
        add(file.name, fileType(file.name), humanSize(file.size));
      });
    });

    document.querySelectorAll(".fm-file-row").forEach((row) => {
      const name = row.querySelector(".fm-file-name")?.textContent?.trim();
      const size = row.querySelector(".fm-file-size")?.textContent?.trim() || "Selected evidence";
      add(name, fileType(name), size);
    });

    if (!evidence.length && typeof window.getFundManagerCase === "function") {
      const caseData = window.getFundManagerCase();
      (caseData?.classification?.sources || []).forEach((source) => {
        const status = source.validation_status === "accepted" ? "Accepted case evidence" : "Evidence under review";
        add(source.filename, fileType(source.filename, source.detected_type), status);
      });
    }

    return evidence;
  }

  function installAnalysisTheatre() {
    const overlay = document.querySelector("#loading");
    if (!overlay || overlay.dataset.analysisTheatre === "true") return;
    overlay.dataset.analysisTheatre = "true";
    overlay.classList.add("analysis-loading");
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");

    if (!document.querySelector(`link[href="${ANALYSIS_STYLE}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = ANALYSIS_STYLE;
      document.head.appendChild(link);
    }

    overlay.innerHTML = `
      <div class="analysis-theatre" aria-label="Cherry evidence analysis control room">
        <div class="analysis-topline">
          <div class="analysis-brand">
            <div class="analysis-brand-mark" aria-hidden="true">C</div>
            <div><small>Cherry FundOps</small><strong>Evidence Control Room</strong></div>
          </div>
          <div class="analysis-live"><i aria-hidden="true"></i><em class="analysis-live-label" id="analysis-live-label">ANALYSIS REQUEST IN FLIGHT</em><b id="analysis-elapsed">0s</b></div>
        </div>

        <div class="analysis-grid">
          <section class="analysis-panel analysis-evidence-panel">
            <p class="analysis-kicker">Evidence in</p>
            <div class="analysis-evidence-count"><strong id="analysis-evidence-count">0</strong><span id="analysis-evidence-label">sources in scope</span></div>
            <div class="analysis-files" id="analysis-files"></div>
            <div class="analysis-more" id="analysis-more" hidden></div>
          </section>

          <section class="analysis-panel analysis-centre">
            <div>
              <div class="analysis-core-wrap" aria-hidden="true">
                <div class="analysis-ring"></div>
                <div class="analysis-ring two"></div>
                <div class="analysis-core"><b>C</b></div>
                <div class="analysis-satellite one">PDF</div>
                <div class="analysis-satellite two">XLSX</div>
                <div class="analysis-satellite three">RULE</div>
                <div class="analysis-satellite four">TRACE</div>
              </div>
              <div class="analysis-centre-copy">
                <h2 id="analysis-title">Turning evidence into a <em>review-ready control map.</em></h2>
                <p id="analysis-subtitle">One bounded request is in flight. Cherry shows completed financial results only when the server returns them.</p>
              </div>
            </div>
            <div class="analysis-path-wrap">
              <div class="analysis-path-label"><span>Governed control architecture</span><span>Sequence · not fake progress</span></div>
              <div class="analysis-path">
                <div><b>01</b><span>Recognise</span></div>
                <div><b>02</b><span>Route</span></div>
                <div><b>03</b><span>Control</span></div>
                <div><b>04</b><span>Exceptions</span></div>
                <div><b>05</b><span>Human gate</span></div>
              </div>
            </div>
          </section>

          <aside class="analysis-panel analysis-insight-panel">
            <p class="analysis-kicker">Built to explain itself</p>
            <div class="analysis-principle" id="analysis-principle">
              <span>Control principle</span>
              <strong id="analysis-principle-title">No silent guesses.</strong>
              <p id="analysis-principle-body">Ambiguous evidence stays visible for review instead of being quietly promoted to financial truth.</p>
            </div>
            <div class="analysis-proof">
              <div><span>Financial writes</span><strong>None</strong></div>
              <div><span>Payment authority</span><strong>None</strong></div>
              <div><span>Final decision</span><strong>Fund manager</strong></div>
            </div>
          </aside>
        </div>

        <div class="analysis-footer">
          <div class="analysis-ticker"><i aria-hidden="true"></i><p id="analysis-narrative">${escapeHtml(NARRATIVES[0])}</p></div>
          <small>The API returns the completed result as one response. This screen explains the governed path without inventing a percentage or pretending intermediate stages have completed.</small>
        </div>
      </div>`;

    const originalLoading = typeof window.loading === "function"
      ? window.loading
      : null;
    let startedAt = 0;
    let elapsedTimer = null;
    let principleTimer = null;
    let narrativeTimer = null;
    let principleIndex = 0;
    let narrativeIndex = 0;

    const stopTimers = () => {
      if (elapsedTimer) window.clearInterval(elapsedTimer);
      if (principleTimer) window.clearInterval(principleTimer);
      if (narrativeTimer) window.clearInterval(narrativeTimer);
      elapsedTimer = null;
      principleTimer = null;
      narrativeTimer = null;
    };

    const updateElapsed = () => {
      const node = document.querySelector("#analysis-elapsed");
      if (!node || !startedAt) return;
      const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      node.textContent = seconds < 60
        ? `${seconds}s`
        : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
    };

    const swapPrinciple = () => {
      principleIndex = (principleIndex + 1) % PRINCIPLES.length;
      const card = document.querySelector("#analysis-principle");
      const title = document.querySelector("#analysis-principle-title");
      const body = document.querySelector("#analysis-principle-body");
      if (!card || !title || !body) return;
      title.textContent = PRINCIPLES[principleIndex].title;
      body.textContent = PRINCIPLES[principleIndex].body;
      card.classList.remove("swap");
      void card.offsetWidth;
      card.classList.add("swap");
    };

    const swapNarrative = () => {
      narrativeIndex = (narrativeIndex + 1) % NARRATIVES.length;
      const node = document.querySelector("#analysis-narrative");
      if (!node) return;
      node.textContent = NARRATIVES[narrativeIndex];
      node.classList.remove("swap");
      void node.offsetWidth;
      node.classList.add("swap");
    };

    const prepareEvidence = () => {
      const evidence = collectEvidence();
      const count = document.querySelector("#analysis-evidence-count");
      const label = document.querySelector("#analysis-evidence-label");
      const files = document.querySelector("#analysis-files");
      const more = document.querySelector("#analysis-more");
      const title = document.querySelector("#analysis-title");
      const subtitle = document.querySelector("#analysis-subtitle");
      const liveLabel = document.querySelector("#analysis-live-label");
      const clearing = document.querySelector("#clear-data-dialog[open]");
      const caseData = typeof window.getFundManagerCase === "function"
        ? window.getFundManagerCase()
        : null;

      if (count) count.textContent = evidence.length;
      if (label) label.textContent = evidence.length === 1 ? "source in scope" : "sources in scope";
      if (files) {
        files.innerHTML = evidence.slice(0, 4).map((item) => `
          <div class="analysis-file">
            <b class="analysis-file-type">${escapeHtml(item.type)}</b>
            <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.meta)}</small></div>
          </div>`).join("") || `
          <div class="analysis-file">
            <b class="analysis-file-type">CASE</b>
            <div><strong>${escapeHtml(caseData?.case_id || "Governed request")}</strong><small>Waiting for the completed server response</small></div>
          </div>`;
      }
      if (more) {
        const remaining = Math.max(0, evidence.length - 4);
        more.hidden = remaining === 0;
        more.textContent = remaining ? `+ ${remaining} more source${remaining === 1 ? "" : "s"} in this request` : "";
      }

      if (clearing) {
        if (title) title.innerHTML = "Clearing the <em>temporary review workspace.</em>";
        if (subtitle) subtitle.textContent = "Selected evidence and ephemeral workflow state are being cleared before the next case.";
        if (liveLabel) liveLabel.textContent = "WORKSPACE RESET IN FLIGHT";
      } else if (evidence.length) {
        if (title) title.innerHTML = `${evidence.length} source${evidence.length === 1 ? "" : "s"} moving toward a <em>review-ready control map.</em>`;
        if (subtitle) subtitle.textContent = "Cherry keeps the request visible while the server detects the workflow, runs the applicable controls and returns the completed findings.";
        if (liveLabel) liveLabel.textContent = "ANALYSIS REQUEST IN FLIGHT";
      } else {
        if (title) title.innerHTML = "Cherry is running a <em>governed control request.</em>";
        if (subtitle) subtitle.textContent = "The UI will change only when the server returns a completed control result; no intermediate completion is fabricated in the browser.";
        if (liveLabel) liveLabel.textContent = "CONTROL REQUEST IN FLIGHT";
      }
    };

    window.loading = function enhancedLoading(visible) {
      if (visible) {
        prepareEvidence();
        startedAt = Date.now();
        principleIndex = 0;
        narrativeIndex = 0;
        const principleTitle = document.querySelector("#analysis-principle-title");
        const principleBody = document.querySelector("#analysis-principle-body");
        const narrative = document.querySelector("#analysis-narrative");
        if (principleTitle) principleTitle.textContent = PRINCIPLES[0].title;
        if (principleBody) principleBody.textContent = PRINCIPLES[0].body;
        if (narrative) narrative.textContent = NARRATIVES[0];
        overlay.setAttribute("aria-busy", "true");
        if (originalLoading) originalLoading(true);
        else overlay.classList.remove("hidden");
        stopTimers();
        updateElapsed();
        elapsedTimer = window.setInterval(updateElapsed, 1000);
        principleTimer = window.setInterval(swapPrinciple, 4300);
        narrativeTimer = window.setInterval(swapNarrative, 3400);
        return;
      }

      stopTimers();
      startedAt = 0;
      overlay.setAttribute("aria-busy", "false");
      if (originalLoading) originalLoading(false);
      else overlay.classList.add("hidden");
    };
  }

  function init() {
    installAnalysisTheatre();
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
