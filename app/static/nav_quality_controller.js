(() => {
  "use strict";

  const CASE_KEY = "cherry_fund_manager_case_id";
  const NAV_TYPES = new Set([
    "nav_summary",
    "nav_workbook",
    "investor_gl",
    "side_letter_rules",
    "side_letter",
    "lpa",
  ]);
  const STEPS = ["NAV Evidence", "Readiness", "Reconcile", "Exception Review", "Decision"];
  const state = { caseData: null, history: null, busy: false, viewStep: null };

  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const workflow = () => state.caseData?.workflows?.nav_quality_controller || {};
  const notify = (message, error = false) => (
    typeof toast === "function" ? toast(message, error) : error && console.error(message)
  );

  function currentStep() {
    const nav = workflow();
    if (!state.caseData) return 0;
    if (nav.decision) return 4;
    if (nav.review) return 3;
    if (nav.reconciliation) return 2;
    if (nav.readiness) return 1;
    return 0;
  }

  function displayedStep() {
    return state.viewStep == null ? currentStep() : Math.min(state.viewStep, currentStep());
  }

  function navApplicable(caseData = state.caseData) {
    const sources = caseData?.classification?.sources || [];
    return sources.some((source) => (
      source.validation_status === "accepted" && NAV_TYPES.has(source.detected_type)
    ));
  }

  function syncNavTabAvailability() {
    const navButton = document.querySelector('[data-fm-tab="nav"]');
    if (!navButton) return;

    const available = Boolean(state.caseData && navApplicable());
    navButton.disabled = !available;
    navButton.setAttribute("aria-disabled", String(!available));
    navButton.title = available
      ? "Open NAV Quality Controller"
      : state.caseData
        ? "NAV Quality Controller is available when recognised NAV evidence exists in this case."
        : "Upload evidence and create a case before starting NAV Quality Control.";

    if (!available && navButton.classList.contains("active")) {
      window.setFundManagerTab?.("general");
    }
  }

  function rememberCase(payload, { broadcast = true } = {}) {
    if (!payload?.case_id) return;
    state.caseData = payload;
    state.viewStep = null;
    localStorage.setItem(CASE_KEY, payload.case_id);
    render();
    queueMicrotask(syncNavTabAvailability);
    if (broadcast) {
      window.dispatchEvent(new CustomEvent("fund-manager-case-updated", { detail: payload }));
    }
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    let payload = {};
    try { payload = await response.json(); } catch { payload = {}; }
    if (!response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : `${response.status} ${response.statusText}`);
    }
    return payload;
  }

  function injectStyles() {
    if (document.querySelector('link[href="/static/nav_quality_controller.css"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/nav_quality_controller.css";
    document.head.appendChild(link);
  }

  function mount() {
    if (document.querySelector("#nav-quality-controller")) return;
    const anchor = document.querySelector("#fund-manager") || document.querySelector(".source-strip");
    if (!anchor) return;
    anchor.insertAdjacentHTML(
      "afterend",
      '<section class="navqc-shell" id="nav-quality-controller" hidden><div class="navqc-card"><div id="navqc-content"></div></div></section>',
    );
    render();
    syncNavTabAvailability();
  }

  function pill(status) {
    const value = String(status || "review");
    return `<span class="navqc-pill ${esc(value)}">${esc(value.replaceAll("_", " "))}</span>`;
  }

  function header() {
    return `<div class="navqc-head"><div><p class="eyebrow">Fund Manager · NAV controls</p><h2>NAV Quality Controller</h2>
      <p>Uses the evidence already uploaded to this case. Add only new or missing evidence when required.</p></div>
      <div class="navqc-actions"><span class="navqc-case">${state.caseData ? `Case ${esc(state.caseData.case_id)}` : "No active case"}</span>
      <button type="button" class="navqc-button secondary" id="navqc-exit">← Back to General Document Review</button></div></div>`;
  }

  function stepper() {
    const current = currentStep();
    const viewing = displayedStep();
    return `<div class="navqc-stepper">${STEPS.map((label, index) => {
      const cls = index < current ? "done" : index === current ? "active" : "";
      const historical = index === viewing && viewing !== current ? " viewing" : "";
      return `<div class="navqc-step ${cls}${historical}"><span>${index + 1}</span><strong>${label}</strong></div>`;
    }).join("")}</div>`;
  }

  function backButton() {
    return displayedStep() > 0
      ? '<button class="navqc-button secondary" id="navqc-back">← Back</button>'
      : "";
  }

  function historicalNav() {
    if (displayedStep() === currentStep()) return "";
    return '<button class="navqc-button primary" id="navqc-current-step">Return to current step</button>';
  }

  function noCase() {
    return '<div class="navqc-panel"><h3>Upload evidence first</h3><div class="navqc-empty">NAV Quality Control starts only after a Fund Manager case has been created and NAV-related evidence is recognised.</div></div>';
  }

  function evidenceUploadPanel() {
    return `<details class="navqc-boundary"><summary>Add new or missing evidence</summary>
      <p>Only the newly selected file is sent. Existing case evidence is not uploaded again.</p>
      <div class="navqc-actions"><input type="file" id="navqc-new-evidence"><button class="navqc-button secondary" id="navqc-upload-new-evidence">Add evidence</button></div></details>`;
  }

  function evidence() {
    const sources = state.caseData?.classification?.sources || [];
    const relevant = sources.filter((source) => NAV_TYPES.has(source.detected_type));
    const current = currentStep() === 0;
    return `<div class="navqc-panel"><h3>NAV Evidence</h3><p>Confirm the NAV-related evidence recognised in this case before checking readiness.</p>
      <div class="navqc-grid">${relevant.map((source) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(source.filename)}</strong>${pill(source.validation_status === "accepted" ? "ready" : "review")}</div><p>${esc(source.detected_type)}</p></div>`).join("") || '<div class="navqc-empty">No NAV-specific evidence identified yet.</div>'}</div>
      ${current ? evidenceUploadPanel() : ""}<div class="navqc-actions">${current ? '<button class="navqc-button primary" id="navqc-readiness">Check readiness →</button>' : historicalNav()}</div></div>`;
  }

  function readinessView(readiness) {
    const inputs = readiness.inputs || {};
    const rows = [
      ["Administrator NAV summary", inputs.nav_summary],
      ["Investor-level GL", inputs.source_ledger],
      ["Structured side-letter rules", inputs.side_letter_rules],
    ];
    const current = currentStep() === 1;
    return `<div class="navqc-panel"><h3>Readiness</h3><p>Confirm the required NAV inputs before reconciliation.</p>
      <div class="navqc-grid">${rows.map(([label, item]) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(label)}</strong>${pill(item ? "ready" : "optional_evidence")}</div><p>${item ? esc(item.filename) : "Not supplied / not identified"}</p></div>`).join("")}</div>
      ${(readiness.blockers || []).map((blocker) => `<div class="navqc-blocker">${esc(blocker)}</div>`).join("")}
      ${current ? evidenceUploadPanel() : ""}<div class="navqc-actions">${backButton()}${current ? `<button class="navqc-button primary" id="navqc-reconcile" ${readiness.status === "ready" ? "" : "disabled"}>Run reconciliation →</button><button class="navqc-button secondary" id="navqc-refresh">Recheck readiness</button>` : historicalNav()}</div></div>`;
  }

  function exceptionKey(finding, index) {
    return String(finding.code || finding.issue_id || finding.title || `exception-${index + 1}`)
      .replace(/[^a-zA-Z0-9_.-]/g, "-")
      .slice(0, 120);
  }

  function exceptionCard(finding, index) {
    const key = exceptionKey(finding, index);
    const resolution = workflow().exception_resolutions?.[key];
    const ignored = resolution?.status === "ignored";
    return `<article class="navqc-finding" data-exception="${esc(key)}"><header><strong>${esc(finding.title || finding.code || `Exception ${index + 1}`)}</strong>${pill(ignored ? "ignored" : finding.severity)}</header>
      <p>${esc(finding.detail)}</p>${finding.expected != null ? `<p><strong>Expected:</strong> ${esc(finding.expected)} · <strong>Observed:</strong> ${esc(finding.observed)}</p>` : ""}
      ${resolution ? `<div class="navqc-boundary"><strong>${esc(resolution.status.replaceAll("_", " "))}</strong>${resolution.filename ? ` · ${esc(resolution.filename)}` : ""}${resolution.reason ? ` · ${esc(resolution.reason)}` : ""}</div>` : ""}
      <div class="navqc-actions"><button class="navqc-button primary" data-upload-exception="${esc(key)}">Upload evidence</button><input type="file" hidden data-exception-file="${esc(key)}">
      <button class="navqc-button secondary" data-ignore-exception="${esc(key)}" ${ignored ? "disabled" : ""}>Ignore</button><button class="navqc-button secondary" data-details-exception="${esc(key)}">Details</button></div>
      <div class="navqc-boundary" data-exception-details="${esc(key)}" hidden>Upload one new supporting file for this exception, or ignore it with a recorded reason.</div></article>`;
  }

  function reconciliationView(result) {
    const review = result.review || {};
    const findings = review.findings || [];
    const current = currentStep() === 2;
    return `<div class="navqc-panel"><h3>Reconcile</h3><div class="navqc-metrics"><div><span>Controls passed</span><strong>${esc(review.controls_passed ?? 0)}</strong></div>
      <div><span>Exceptions</span><strong>${esc(review.exceptions_open ?? findings.length)}</strong></div><div><span>Round</span><strong>${esc(result.iteration?.round_number ?? 1)}</strong></div></div>
      <p>Resolve each exception with supporting evidence or an explicit ignore decision.</p><div>${findings.map(exceptionCard).join("") || '<div class="navqc-empty">No NAV exceptions were returned.</div>'}</div>
      <div class="navqc-actions">${backButton()}${current ? '<button class="navqc-button primary" id="navqc-review">Review exceptions →</button><button class="navqc-button secondary" id="navqc-history">View history</button>' : historicalNav()}</div></div>`;
  }

  function reviewView(review) {
    const items = review.investigations || [];
    const current = currentStep() === 3;
    return `<div class="navqc-panel"><h3>Exception Review</h3><p>${esc(review.agent_summary || "Review the consolidated NAV findings and recommended action.")}</p>
      ${items.map((item) => `<article class="navqc-finding"><header><strong>${esc(item.issue_id || "NAV finding")}</strong>${pill(item.priority)}</header><p>${esc(item.finding)}</p>${item.evidence_gap ? `<p><strong>Evidence gap:</strong> ${esc(item.evidence_gap)}</p>` : ""}<p><strong>Recommended action:</strong> ${esc(item.recommended_action)}</p></article>`).join("")}
      <div class="navqc-actions">${backButton()}${current ? '<button class="navqc-button primary" id="navqc-decision-step">Continue to decision →</button>' : historicalNav()}</div></div>`;
  }

  function decisionView(review) {
    return `<div class="navqc-panel"><h3>Decision</h3><p>Record the NAV outcome after reviewing reconciliation results and exceptions.</p>
      <div class="navqc-decision"><p>Agent recommendation: <strong>${esc(String(review?.recommended_human_action || "review").replaceAll("_", " "))}</strong></p>
      <input id="navqc-note" type="text" placeholder="Optional Fund Manager decision note"><div class="navqc-actions">
      <button class="navqc-button primary" data-nav-decision="approve_nav">Approve NAV</button><button class="navqc-button secondary" data-nav-decision="approve_with_exception">Approve with exception</button>
      <button class="navqc-button secondary" data-nav-decision="request_evidence">Request evidence</button><button class="navqc-button danger" data-nav-decision="escalate">Escalate</button></div></div>
      <div class="navqc-actions"><button class="navqc-button secondary" id="navqc-back">← Back</button></div></div>`;
  }

  function decidedView(decision) {
    return `<div class="navqc-panel"><h3>NAV decision recorded</h3><p><strong>${esc(String(decision.action || "recorded").replaceAll("_", " "))}</strong></p>
      ${decision.note ? `<p>${esc(decision.note)}</p>` : ""}<div class="navqc-actions"><button class="navqc-button secondary" id="navqc-back">← Back</button><button class="navqc-button secondary" id="navqc-history">View history</button></div></div>`;
  }

  function historyView() {
    if (!state.history) return "";
    if (!state.history.available) {
      return `<div class="navqc-panel"><h3>Review history</h3><div class="navqc-empty">${esc(state.history.reason)}</div></div>`;
    }
    const history = state.history.history || {};
    const rounds = history.history || history.rounds || history.iterations || [];
    return `<div class="navqc-panel"><h3>Review history</h3><div class="navqc-history">${rounds.map((round) => `<div class="navqc-round"><span>Round ${esc(round.round_number)}</span><strong>${esc(String(round.action || "review").replaceAll("_", " "))}</strong><span>${esc(round.exceptions_open ?? 0)} exceptions</span></div>`).join("")}</div></div>`;
  }

  function render() {
    const root = document.querySelector("#navqc-content");
    if (!root) return;
    const nav = workflow();
    let body = noCase();
    if (state.caseData) {
      const view = displayedStep();
      if (view === 0) body = evidence();
      else if (view === 1) body = readinessView(nav.readiness || {});
      else if (view === 2) body = reconciliationView(nav.reconciliation || {});
      else if (view === 3) body = reviewView(nav.review || {});
      else body = nav.decision ? decidedView(nav.decision) : decisionView(nav.review || {});
    }
    root.innerHTML = `${header()}${stepper()}${body}${historyView()}`;
    bind();
  }

  async function run(path, options = { method: "POST" }) {
    if (state.busy || !state.caseData) return;
    state.busy = true;
    try {
      rememberCase(await api(path, options));
    } catch (error) {
      notify(error.message || "NAV workflow step failed.", true);
    } finally {
      state.busy = false;
    }
  }

  async function uploadGenericEvidence() {
    const input = document.querySelector("#navqc-new-evidence");
    const file = input?.files?.[0];
    if (!file || !state.caseData) return;
    const form = new FormData();
    form.append("files", file);
    await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/evidence`, {
      method: "POST",
      body: form,
    });
    notify("Evidence added. NAV workflow state has been refreshed.");
  }

  async function uploadEvidence(key, file) {
    if (!file || state.busy) return;
    const form = new FormData();
    form.append("file", file);
    await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/evidence`, {
      method: "POST",
      body: form,
    });
    notify("Supporting evidence added to this exception.");
  }

  async function ignoreException(key) {
    const reason = window.prompt("Reason for ignoring this exception (required):");
    if (!reason?.trim()) return;
    const note = window.prompt("Optional supporting note:") || null;
    await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/ignore`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason.trim(), note }),
    });
    notify("Exception ignored with an auditable reason.");
  }

  async function loadHistory() {
    try {
      state.history = await api(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/history`);
      render();
    } catch (error) {
      notify(error.message, true);
    }
  }

  function goBack() {
    state.viewStep = Math.max(0, displayedStep() - 1);
    render();
  }

  function bind() {
    const id = state.caseData?.case_id;
    document.querySelector("#navqc-exit")?.addEventListener("click", () => {
      window.setFundManagerTab?.("general");
    });
    document.querySelector("#navqc-back")?.addEventListener("click", goBack);
    document.querySelector("#navqc-current-step")?.addEventListener("click", () => {
      state.viewStep = null;
      render();
    });
    document.querySelector("#navqc-readiness")?.addEventListener("click", () => {
      run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`);
    });
    document.querySelector("#navqc-refresh")?.addEventListener("click", () => {
      run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`);
    });
    document.querySelector("#navqc-reconcile")?.addEventListener("click", () => {
      run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/reconcile`);
    });
    document.querySelector("#navqc-review")?.addEventListener("click", () => {
      run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/review`);
    });
    document.querySelector("#navqc-decision-step")?.addEventListener("click", () => {
      state.viewStep = 4;
      render();
    });
    document.querySelector("#navqc-history")?.addEventListener("click", loadHistory);
    document.querySelector("#navqc-upload-new-evidence")?.addEventListener("click", uploadGenericEvidence);
    document.querySelectorAll("[data-upload-exception]").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelector(`[data-exception-file="${CSS.escape(button.dataset.uploadException)}"]`)?.click();
      });
    });
    document.querySelectorAll("[data-exception-file]").forEach((input) => {
      input.addEventListener("change", () => uploadEvidence(input.dataset.exceptionFile, input.files?.[0]));
    });
    document.querySelectorAll("[data-ignore-exception]").forEach((button) => {
      button.addEventListener("click", () => ignoreException(button.dataset.ignoreException));
    });
    document.querySelectorAll("[data-details-exception]").forEach((button) => {
      button.addEventListener("click", () => {
        const details = document.querySelector(`[data-exception-details="${CSS.escape(button.dataset.detailsException)}"]`);
        if (details) details.hidden = !details.hidden;
      });
    });
    document.querySelectorAll("[data-nav-decision]").forEach((button) => {
      button.addEventListener("click", () => {
        run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/decision`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: button.dataset.navDecision,
            note: document.querySelector("#navqc-note")?.value || null,
          }),
        });
      });
    });
  }

  async function restore() {
    const id = localStorage.getItem(CASE_KEY);
    if (!id) return;
    try {
      rememberCase(await api(`/api/fund-manager/cases/${encodeURIComponent(id)}`), { broadcast: false });
    } catch {
      localStorage.removeItem(CASE_KEY);
    }
  }

  window.addEventListener("fund-manager-case-updated", (event) => {
    if (event.detail?.case_id) rememberCase(event.detail, { broadcast: false });
  });
  window.addEventListener("fund-manager-case-cleared", () => {
    state.caseData = null;
    state.history = null;
    state.viewStep = null;
    window.setFundManagerTab?.("general");
    render();
    queueMicrotask(syncNavTabAvailability);
  });
  window.addEventListener("fund-manager-nav-tab-opened", () => {
    if (!navApplicable()) {
      window.setFundManagerTab?.("general");
      return;
    }
    render();
  });

  injectStyles();
  document.addEventListener("DOMContentLoaded", async () => {
    mount();
    await restore();
    syncNavTabAvailability();
    window.setFundManagerTab?.("general");
  });
})();