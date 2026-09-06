(() => {
  "use strict";

  const REQUEST_COOLDOWN_MS = 5000;
  const REQUEST_TIMEOUT_MS = 120000;
  const CASE_KEY = "cherry_fund_manager_case_id";
  const TAB_KEY = "cherry_fund_manager_active_tab";
  const STEPS = [
    ["classified", "Evidence Review"],
    ["planned", "Review Plan"],
    ["executed", "Control Results"],
    ["investigated", "Findings Review"],
    ["decided", "Decision"],
  ];
  const state = {
    files: [],
    caseData: null,
    busy: false,
    lastRequestAt: new Map(),
    viewStep: null,
    showDecision: false,
  };

  const TYPE_LABELS = {
    nav_workbook: "NAV workbook",
    investor_gl: "Investor-level GL",
    lp_commitments: "LP commitments",
    bank_statement_working_file: "Bank statement working file",
    loader_template: "Loader / mapping workbook",
    capital_call_notice: "Capital-call notice",
    lpa: "Limited Partnership Agreement",
    side_letter: "Side letter",
    bank_statement: "Bank statement",
    financial_statement: "Financial statements",
    investor_report: "Investor report",
    positions: "Positions",
    trades: "Trades",
    bank_transactions: "Bank transactions",
    cash_transactions: "Cash transactions",
  };

  const q = (selector, root = document) => root.querySelector(selector);
  const qAll = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function notify(message, error = false) {
    if (typeof toast === "function") return toast(message, error);
    if (error) console.error(message);
  }

  function injectStyles() {
    if (q('link[href="/static/fund_manager.css"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/fund_manager.css";
    document.head.appendChild(link);
  }

  function shellMarkup() {
    return `<div class="fm-workflow-tabs" id="fm-workflow-tabs" role="tablist" aria-label="Fund Manager workflow">
      <button type="button" class="active" role="tab" aria-selected="true" data-fm-tab="general">General Document Review</button>
      <button type="button" role="tab" aria-selected="false" data-fm-tab="nav" disabled>NAV Quality Controller</button>
    </div>
    <section class="fm-shell" id="fund-manager" aria-labelledby="fm-title"><div class="fm-inner">
      <div class="fm-head"><p class="fm-kicker">Cherry Fund Manager · document controls</p>
      <h2 id="fm-title">General Document Review</h2>
      <p>Upload evidence once, review the proposed controls, inspect results and findings, then record a decision.</p></div>
      <div class="fm-card"><div id="fm-stepper"></div><div id="fm-stage" aria-live="polite"></div></div>
    </div></section>`;
  }

  function mountShell() {
    if (q("#fund-manager")) return;
    const sourceStrip = q(".source-strip");
    if (sourceStrip) sourceStrip.insertAdjacentHTML("afterend", shellMarkup());
  }

  function currentIndex() {
    if (!state.caseData) return 0;
    return Math.max(0, STEPS.findIndex(([stage]) => stage === state.caseData.stage));
  }

  function displayedIndex() {
    return state.viewStep == null ? currentIndex() : Math.min(state.viewStep, currentIndex());
  }

  function setTab(tab) {
    const requested = tab === "nav" && state.caseData ? "nav" : "general";
    const general = q("#fund-manager");
    const nav = q("#nav-quality-controller");
    if (general) general.hidden = requested !== "general";
    if (nav) nav.hidden = requested !== "nav";
    qAll("[data-fm-tab]").forEach((button) => {
      const active = button.dataset.fmTab === requested;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    localStorage.setItem(TAB_KEY, requested);
    if (requested === "nav") window.dispatchEvent(new CustomEvent("fund-manager-nav-tab-opened"));
  }

  function refreshTabAvailability() {
    const navButton = q('[data-fm-tab="nav"]');
    if (navButton) navButton.disabled = !state.caseData;
    setTab(localStorage.getItem(TAB_KEY) || "general");
  }

  function rememberCase(payload, { broadcast = true } = {}) {
    if (!payload?.case_id) return;
    state.caseData = payload;
    state.files = [];
    state.viewStep = null;
    state.showDecision = false;
    localStorage.setItem(CASE_KEY, payload.case_id);
    render();
    refreshTabAvailability();
    if (broadcast) {
      window.dispatchEvent(new CustomEvent("fund-manager-case-updated", { detail: payload }));
    }
  }

  function renderStepper() {
    const target = q("#fm-stepper");
    if (!target) return;
    const current = currentIndex();
    const active = displayedIndex();
    target.innerHTML = `<div class="fm-stepper">${STEPS.map(([, label], index) => {
      const cls = index < current ? "done" : index === current ? "active" : "";
      const viewing = index === active && active !== current ? " viewing" : "";
      return `<div class="fm-step ${cls}${viewing}"><span>${index + 1}</span><strong>${esc(label)}</strong></div>`;
    }).join("")}</div>`;
  }

  function humanSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function buildEvidenceForm() {
    const form = new FormData();
    for (const file of state.files) form.append("files", file, file.name);
    return form;
  }

  async function request(path, options = {}) {
    const now = Date.now();
    const last = state.lastRequestAt.get(path) || 0;
    const remaining = REQUEST_COOLDOWN_MS - (now - last);
    if (remaining > 0) {
      throw new Error(`Please wait ${Math.ceil(remaining / 1000)} seconds before retrying.`);
    }
    state.lastRequestAt.set(path, now);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(path, { ...options, signal: controller.signal });
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("The request timed out. Please try again.");
      }
      throw new Error("Could not reach the server. Check your connection and try again.");
    } finally {
      clearTimeout(timeoutId);
    }

    let body = {};
    try { body = await response.json(); } catch { body = {}; }
    if (!response.ok) {
      throw new Error(typeof body.detail === "string" ? body.detail : `${response.status} ${response.statusText}`);
    }
    return body;
  }

  async function runAction(action, successMessage = null) {
    if (state.busy) return;
    state.busy = true;
    if (typeof loading === "function") loading(true);
    try {
      rememberCase(await action());
      if (successMessage) notify(successMessage);
    } catch (error) {
      notify(error.message || "Fund Manager step failed.", true);
    } finally {
      state.busy = false;
      if (typeof loading === "function") loading(false);
      render();
    }
  }

  function typeLabel(type) { return TYPE_LABELS[type] || type || "Unknown"; }

  function sourceCard(source) {
    const accepted = source.validation_status === "accepted";
    const warnings = (source.validation_errors || source.warnings || [])
      .map((item) => `<div class="fm-warning">${esc(item)}</div>`).join("");
    return `<div class="fm-source-card${accepted ? "" : " unknown"}">
      <div class="fm-source-icon">${esc(source.id?.replace("SRC-", "") || "?")}</div>
      <div class="fm-source-body"><strong>${esc(source.filename)}</strong><p>${esc(typeLabel(source.detected_type))}</p>${warnings}</div>
      <span class="fm-pill ${accepted ? "ok" : "review"}">${accepted ? "Accepted" : "Review"}</span></div>`;
  }

  function statusPill(status) {
    if (["ready", "executed", "completed", "info"].includes(status)) {
      return `<span class="fm-pill ok">${esc(status)}</span>`;
    }
    if (["failed", "high"].includes(status)) {
      return `<span class="fm-pill error">${esc(status)}</span>`;
    }
    return `<span class="fm-pill review">${esc((status || "review").replaceAll("_", " "))}</span>`;
  }

  function planRows(plan) {
    return (plan?.control_plan || []).map((entry) => `<div class="fm-plan-row">
      <span class="fm-plan-file">${esc((entry.source_ids || []).join(", "))}</span>
      <span class="fm-plan-control">${esc(entry.control)}</span>${statusPill(entry.status)}
      ${entry.reasoning ? `<small class="fm-plan-reason">${esc(entry.reasoning)}</small>` : ""}</div>`).join("");
  }

  function issueCards(execution) {
    const issues = execution?.issues || [];
    if (!issues.length) return '<div class="fm-empty">No issues were returned by the executed controls.</div>';
    return `<div class="fm-issue-grid">${issues.map((issue) => `<div class="fm-issue-card">
      <div class="fm-issue-head"><strong>${esc(issue.title)}</strong>${statusPill(issue.severity)}</div>
      <p>${esc(issue.summary)}</p><p class="fm-issue-action"><strong>Recommended action:</strong> ${esc(issue.recommended_action)}</p></div>`).join("")}</div>`;
  }

  function pendingFileRows() {
    return state.files.map((file, index) => `<div class="fm-file-row">
      <span class="fm-file-name">${esc(file.name)}</span><span class="fm-file-size">${esc(humanSize(file.size))}</span>
      <button type="button" data-remove-file="${index}" aria-label="Remove ${esc(file.name)}">✕</button></div>`).join("");
  }

  function addEvidencePanel() {
    if (!state.caseData) return "";
    return `<details class="fm-control-plan fm-add-evidence"><summary>Add new or missing evidence</summary>
      <div class="fm-boundary">Only newly selected files are submitted. Existing case evidence is not uploaded again. Adding evidence resets results that depended on the previous evidence set.</div>
      <div class="fm-dropzone compact" id="fm-dropzone"><strong>Add new evidence</strong><span>PDF · XLSX · CSV · JSON · ZIP</span>
      <button type="button" class="fm-button secondary" id="fm-browse">Browse new files</button>
      <input type="file" id="fm-file-input" multiple accept=".pdf,.xlsx,.xls,.csv,.json,.txt,.zip,application/zip,application/x-zip-compressed"></div>
      <div class="fm-file-list">${pendingFileRows()}</div><div class="fm-actions">
      <button type="button" class="fm-button primary" id="fm-add-evidence" ${state.files.length && !state.busy ? "" : "disabled"}>Add selected evidence</button>
      ${state.files.length ? '<button type="button" class="fm-button ghost" id="fm-clear">Clear selection</button>' : ""}</div></details>`;
  }

  function historicalNav() {
    if (displayedIndex() === currentIndex()) return "";
    return `<div class="fm-actions fm-stage-nav"><button type="button" class="fm-button primary" id="fm-current-step">Return to current step</button></div>`;
  }

  function backButton() {
    if (displayedIndex() <= 0) return "";
    return '<button type="button" class="fm-button secondary" id="fm-back">← Back</button>';
  }

  function renderUpload() {
    return `<div class="fm-stage-head"><span class="fm-kicker">Start</span><h3>Upload evidence</h3><p>Create the case with the initial evidence set. No review control runs at this point.</p></div>
      <div class="fm-dropzone" id="fm-dropzone"><strong>Drop evidence here</strong><span>PDF · XLSX · CSV · JSON · ZIP</span>
      <button type="button" class="fm-button secondary" id="fm-browse">Browse files</button>
      <input type="file" id="fm-file-input" multiple accept=".pdf,.xlsx,.xls,.csv,.json,.txt,.zip,application/zip,application/x-zip-compressed"></div>
      <div class="fm-file-list">${pendingFileRows()}</div><div class="fm-actions">
      <button type="button" class="fm-button primary" id="fm-classify" ${state.files.length && !state.busy ? "" : "disabled"}>Create case & review evidence</button>
      ${state.files.length ? '<button type="button" class="fm-button ghost" id="fm-clear">Clear selection</button>' : ""}</div>`;
  }

  function renderClassified() {
    const report = state.caseData.classification;
    const current = currentIndex() === 0;
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 1</span><h3>Evidence Review</h3><p>Confirm what was recognised before Cherry proposes controls.</p></div>
      <div class="fm-inventory-head"><h3>Evidence inventory</h3><span>${esc(report.accepted_count)} accepted · ${esc(report.rejected_count)} review</span></div>
      <div class="fm-source-grid">${(report.sources || []).map(sourceCard).join("")}</div>${current ? addEvidencePanel() : ""}
      <div class="fm-boundary">This step only reviews and classifies the evidence. No control result exists yet.</div>
      ${current ? `<div class="fm-actions fm-stage-nav"><button type="button" class="fm-button primary" id="fm-plan">Build review plan →</button></div>` : historicalNav()}`;
  }

  function renderPlanned() {
    const current = currentIndex() === 1;
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 2</span><h3>Review Plan</h3><p>${esc(state.caseData.plan?.agent_summary || "Review the controls Cherry proposes for the accepted evidence.")}</p></div>
      <div class="fm-plan-grid">${planRows(state.caseData.plan) || '<div class="fm-empty">No applicable controls were planned.</div>'}</div>
      ${current ? addEvidencePanel() : ""}<div class="fm-boundary">Nothing has been executed yet. Only controls marked ready will run.</div>
      <div class="fm-actions fm-stage-nav">${backButton()}${current ? '<button type="button" class="fm-button primary" id="fm-execute">Run approved controls →</button>' : '<button type="button" class="fm-button primary" id="fm-current-step">Return to current step</button>'}</div>`;
  }

  function renderExecuted() {
    const execution = state.caseData.execution;
    const current = currentIndex() === 2 && !state.showDecision;
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 3</span><h3>Control Results</h3><p>${esc(execution?.agent_summary || "Review the deterministic control results and exceptions.")}</p></div>
      <div class="fm-qc-banner ${execution?.status === "clean" ? "ok" : "review"}"><div><span class="fm-kicker">Result</span><strong>${esc((execution?.status || "completed").replaceAll("_", " "))}</strong></div>
      <div class="fm-qc-metrics"><div><span>Issues</span><strong>${esc(execution?.issues_found || 0)}</strong></div><div><span>Material</span><strong>${esc(execution?.material || 0)}</strong></div><div><span>Critical</span><strong>${esc(execution?.critical || 0)}</strong></div></div></div>
      ${issueCards(execution)}<details class="fm-control-plan"><summary>Executed controls</summary><div class="fm-plan-grid">${planRows(execution)}</div></details>
      ${current ? addEvidencePanel() : ""}<div class="fm-actions fm-stage-nav">${backButton()}${current ? '<button type="button" class="fm-button primary" id="fm-investigate">Review findings →</button>' : '<button type="button" class="fm-button primary" id="fm-current-step">Return to current step</button>'}</div>`;
  }

  function renderInvestigated() {
    const investigation = state.caseData.investigation;
    const rows = (investigation?.investigations || []).map((item) => `<div class="fm-issue-card">
      <div class="fm-issue-head"><strong>${esc(item.issue_id || "Finding")}</strong>${statusPill(item.priority)}</div>
      <p>${esc(item.finding)}</p>${item.likely_cause ? `<p><strong>Likely cause:</strong> ${esc(item.likely_cause)}</p>` : ""}
      ${item.evidence_gap ? `<p><strong>Evidence gap:</strong> ${esc(item.evidence_gap)}</p>` : ""}
      <p class="fm-issue-action"><strong>Recommended action:</strong> ${esc(item.recommended_action)}</p></div>`).join("");
    const current = currentIndex() === 3 && !state.showDecision;
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 4</span><h3>Findings Review</h3><p>${esc(investigation?.agent_summary || "Review the findings and recommended actions before deciding.")}</p></div>
      <div class="fm-issue-grid">${rows || '<div class="fm-empty">No additional findings require review.</div>'}</div>${current ? addEvidencePanel() : ""}
      <div class="fm-actions fm-stage-nav">${backButton()}${current ? '<button type="button" class="fm-button primary" id="fm-decision-step">Continue to decision →</button>' : '<button type="button" class="fm-button primary" id="fm-current-step">Return to current step</button>'}</div>`;
  }

  function decisionMarkup() {
    const recommendation = state.caseData.investigation?.recommended_human_action || "review";
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 5</span><h3>Decision</h3><p>Record the human outcome for this document review.</p></div>
      <div class="fm-decision-card"><p>Agent recommendation: <strong>${esc(recommendation.replaceAll("_", " "))}</strong></p>
      <label class="fm-field"><span>Decision note</span><input id="fm-decision-note" type="text" placeholder="Optional rationale or follow-up note"></label>
      <div class="fm-actions"><button class="fm-button primary" data-decision="accept_and_close">Accept & close</button>
      <button class="fm-button secondary" data-decision="request_evidence">Request evidence</button>
      <button class="fm-button secondary" data-decision="assign_and_monitor">Assign for review</button>
      <button class="fm-button danger" data-decision="escalate_immediately">Escalate</button></div></div>
      <div class="fm-actions fm-stage-nav"><button type="button" class="fm-button secondary" id="fm-back-decision">← Back to findings</button></div>`;
  }

  function renderDecided() {
    const decision = state.caseData.decision;
    return `<div class="fm-stage-head"><span class="fm-kicker">Complete</span><h3>Decision recorded</h3><p>Case <code>${esc(state.caseData.case_id)}</code></p></div>
      <div class="fm-qc-banner ok"><div><span class="fm-kicker">Decision</span><strong>${esc((decision?.action || "recorded").replaceAll("_", " "))}</strong></div></div>
      ${decision?.note ? `<div class="fm-boundary"><strong>Note:</strong> ${esc(decision.note)}</div>` : ""}
      <div class="fm-actions fm-stage-nav"><button type="button" class="fm-button secondary" id="fm-back">← Back</button><button type="button" class="fm-button secondary" id="fm-new-case">Start new case</button></div>`;
  }

  function render() {
    renderStepper();
    const target = q("#fm-stage");
    if (!target) return;
    if (!state.caseData) {
      target.innerHTML = renderUpload();
      return;
    }
    if (state.showDecision && ["executed", "investigated"].includes(state.caseData.stage)) {
      target.innerHTML = decisionMarkup();
      return;
    }
    const view = displayedIndex();
    if (view === 0) target.innerHTML = renderClassified();
    else if (view === 1) target.innerHTML = renderPlanned();
    else if (view === 2) target.innerHTML = renderExecuted();
    else if (view === 3) target.innerHTML = renderInvestigated();
    else target.innerHTML = renderDecided();
  }

  function addFiles(fileList) {
    const existing = new Set((state.caseData?.classification?.sources || []).map((source) => source.filename));
    const pending = new Set(state.files.map((file) => `${file.name}:${file.size}`));
    for (const file of [...fileList]) {
      if (existing.has(file.name)) {
        notify(`${file.name} is already stored in this case. Select only new evidence.`, true);
        continue;
      }
      const key = `${file.name}:${file.size}`;
      if (!pending.has(key)) {
        state.files.push(file);
        pending.add(key);
      }
    }
    render();
  }

  function reset() {
    state.files = [];
    state.caseData = null;
    state.viewStep = null;
    state.showDecision = false;
    state.lastRequestAt.clear();
    localStorage.removeItem(CASE_KEY);
    localStorage.setItem(TAB_KEY, "general");
    render();
    refreshTabAvailability();
    window.dispatchEvent(new CustomEvent("fund-manager-case-cleared"));
  }

  function uploadNewEvidence() {
    if (!state.caseData || !state.files.length) return;
    runAction(
      () => request(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/evidence`, {
        method: "POST",
        body: buildEvidenceForm(),
      }),
      "New evidence added. The case has returned to Evidence Review.",
    );
  }

  function goBack() {
    if (state.showDecision) {
      state.showDecision = false;
      state.viewStep = Math.min(3, currentIndex());
    } else {
      state.viewStep = Math.max(0, displayedIndex() - 1);
    }
    render();
  }

  function wireEvents() {
    q("#fm-workflow-tabs")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-fm-tab]");
      if (button && !button.disabled) setTab(button.dataset.fmTab);
    });
    q("#fm-stage")?.addEventListener("click", (event) => {
      const target = event.target.closest("button");
      if (!target) return;
      if (target.id === "fm-browse") q("#fm-file-input")?.click();
      if (target.id === "fm-clear") { state.files = []; render(); }
      if (target.id === "fm-new-case") reset();
      if (target.id === "fm-back" || target.id === "fm-back-decision") goBack();
      if (target.id === "fm-current-step") { state.viewStep = null; state.showDecision = false; render(); }
      if (target.dataset.removeFile !== undefined) {
        state.files.splice(Number(target.dataset.removeFile), 1);
        render();
      }
      if (target.id === "fm-classify") {
        runAction(
          () => request("/api/fund-manager/cases", { method: "POST", body: buildEvidenceForm() }),
          "Evidence uploaded once. Review the recognised evidence before continuing.",
        );
      }
      if (target.id === "fm-add-evidence") uploadNewEvidence();
      if (target.id === "fm-plan") {
        runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/plan`, { method: "POST" }));
      }
      if (target.id === "fm-execute") {
        runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/execute`, { method: "POST" }));
      }
      if (target.id === "fm-investigate") {
        runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/investigate`, { method: "POST" }));
      }
      if (target.id === "fm-decision-step") {
        state.showDecision = true;
        render();
      }
      if (target.dataset.decision) {
        const note = q("#fm-decision-note")?.value || null;
        runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/decision`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: target.dataset.decision, note }),
        }));
      }
    });
    q("#fm-stage")?.addEventListener("change", (event) => {
      if (event.target.id === "fm-file-input") {
        addFiles(event.target.files);
        event.target.value = "";
      }
    });
    q("#fm-stage")?.addEventListener("dragover", (event) => {
      const dropzone = event.target.closest("#fm-dropzone");
      if (!dropzone) return;
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
    q("#fm-stage")?.addEventListener("dragleave", (event) => {
      const dropzone = event.target.closest("#fm-dropzone");
      if (dropzone) dropzone.classList.remove("dragover");
    });
    q("#fm-stage")?.addEventListener("drop", (event) => {
      const dropzone = event.target.closest("#fm-dropzone");
      if (!dropzone) return;
      event.preventDefault();
      dropzone.classList.remove("dragover");
      if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
    });
    window.addEventListener("fund-manager-case-updated", (event) => {
      if (event.detail?.case_id && event.detail.case_id === state.caseData?.case_id) {
        rememberCase(event.detail, { broadcast: false });
      }
    });
  }

  function addNavLink() {
    const nav = q(".primary-nav");
    if (!nav || q('a[href="#fund-manager"]', nav)) return;
    nav.insertAdjacentHTML("afterbegin", '<a href="#fund-manager"><strong>Fund Manager</strong></a>');
  }

  async function restore() {
    const caseId = localStorage.getItem(CASE_KEY);
    if (!caseId) {
      refreshTabAvailability();
      return;
    }
    try {
      const response = await fetch(`/api/fund-manager/cases/${encodeURIComponent(caseId)}`);
      if (!response.ok) throw new Error("Case unavailable");
      rememberCase(await response.json());
    } catch {
      localStorage.removeItem(CASE_KEY);
      state.caseData = null;
      refreshTabAvailability();
    }
  }

  function init() {
    injectStyles();
    mountShell();
    addNavLink();
    wireEvents();
    render();
    refreshTabAvailability();
    restore();
  }

  window.setFundManagerTab = setTab;
  window.getFundManagerCase = () => state.caseData;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();