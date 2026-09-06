(() => {
  "use strict";

  const state = { caseData: null, history: null, busy: false };
  const nativeFetch = window.fetch.bind(window);
  const CASE_KEY = "cherry_fund_manager_case_id";

  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

  function notify(message, error = false) {
    if (typeof toast === "function") toast(message, error);
    else if (error) console.error(message);
  }

  function workflow() {
    return state.caseData?.workflows?.nav_quality_controller || {};
  }

  function rememberCase(payload) {
    if (!payload?.case_id) return;
    state.caseData = payload;
    localStorage.setItem(CASE_KEY, payload.case_id);
    render();
  }

  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const requestUrl = String(args[0] instanceof Request ? args[0].url : args[0]);
    if (requestUrl.includes("/api/fund-manager/cases")) {
      try {
        const clone = response.clone();
        const payload = await clone.json();
        if (payload?.case_id && payload?.classification) rememberCase(payload);
      } catch {
        // Ignore non-JSON and NAV history responses.
      }
    }
    return response;
  };

  async function api(path, options = {}) {
    const response = await nativeFetch(path, options);
    let payload = {};
    try { payload = await response.json(); } catch { payload = {}; }
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `${response.status} ${response.statusText}`);
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
    const general = document.querySelector("#fund-manager");
    const anchor = general || document.querySelector(".source-strip");
    if (!anchor) return;
    anchor.insertAdjacentHTML("afterend", `<section class="navqc-shell" id="nav-quality-controller">
      <div class="navqc-nav"><a href="#fund-manager">General Control Review</a><a class="active" href="#nav-quality-controller">NAV Quality Controller</a></div>
      <div class="navqc-card"><div id="navqc-content"></div></div></section>`);
    render();
  }

  function stageIndex() {
    const nav = workflow();
    if (nav.decision) return 5;
    if (nav.review) return 4;
    if (nav.reconciliation) return 3;
    if (nav.readiness) return 2;
    if (state.caseData) return 1;
    return 0;
  }

  function stepper() {
    const labels = ["Evidence", "NAV readiness", "Reconciliation", "NAV review", "Decision", "History"];
    const active = stageIndex();
    return `<div class="navqc-stepper">${labels.map((label, index) => {
      const step = index + 1;
      const cls = step < active ? "done" : step === active ? "active" : "";
      return `<div class="navqc-step ${cls}"><span>${step}</span><strong>${esc(label)}</strong></div>`;
    }).join("")}</div>`;
  }

  function pill(status) {
    const value = String(status || "review");
    return `<span class="navqc-pill ${esc(value)}">${esc(value.replaceAll("_", " "))}</span>`;
  }

  function header() {
    return `<div class="navqc-head"><div><p class="eyebrow">Fund Manager · specialist workflow</p>
      <h2>NAV Quality Controller</h2><p>Reconcile the administrator NAV pack, investigate deterministic exceptions and record the Fund Manager decision without re-uploading evidence.</p></div>
      <span class="navqc-case">${state.caseData ? `Case ${esc(state.caseData.case_id)}` : "No active Fund Manager case"}</span></div>`;
  }

  function noCase() {
    return `<div class="navqc-panel"><h3>Start with the General Control Review</h3>
      <div class="navqc-empty">Upload and classify evidence in the General Control Review first. The NAV Quality Controller will automatically reuse that case and its stored evidence.</div>
      <div class="navqc-actions"><a class="navqc-button primary" href="#fund-manager">Go to General Control Review</a></div></div>`;
  }

  function evidence() {
    const sources = state.caseData?.classification?.sources || [];
    const navEvidence = sources.filter((source) => ["nav_workbook", "investor_gl", "side_letter", "lpa"].includes(source.detected_type));
    return `<div class="navqc-panel"><h3>Shared case evidence</h3><p>The specialist workflow uses the same case and uploaded evidence as the General Control Review.</p>
      <div class="navqc-grid">${navEvidence.map((source) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(source.filename)}</strong>${pill(source.validation_status === "accepted" ? "ready" : "review")}</div><p>${esc(source.detected_type || "unclassified")}</p></div>`).join("") || '<div class="navqc-empty">No NAV-specific classified evidence was detected. Structured NAV summary JSON can still be identified during NAV readiness.</div>'}</div>
      <div class="navqc-actions"><button class="navqc-button primary" id="navqc-readiness">Assess NAV readiness</button></div></div>`;
  }

  function readinessView(readiness) {
    const inputs = readiness.inputs || {};
    const inputRows = [
      ["Administrator NAV summary", inputs.nav_summary],
      ["Investor-level GL", inputs.source_ledger],
      ["Structured side-letter rules", inputs.side_letter_rules],
    ];
    return `<div class="navqc-panel"><h3>NAV readiness</h3><p>Checks what can run from the evidence already held on this Fund Manager case.</p>
      <div class="navqc-grid">${inputRows.map(([label, item]) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(label)}</strong>${pill(item ? "ready" : "optional_evidence")}</div><p>${item ? esc(item.filename) : "Not supplied / not identified"}</p></div>`).join("")}</div>
      ${(readiness.blockers || []).map((item) => `<div class="navqc-blocker">${esc(item)}</div>`).join("")}
      <div class="navqc-grid">${(readiness.controls || []).map((control) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(control.control)}</strong>${pill(control.status)}</div><p>Requires: ${esc((control.requires || []).join(", "))}</p></div>`).join("")}</div>
      <div class="navqc-boundary">${esc(readiness.control_boundary)}</div>
      <div class="navqc-actions"><button class="navqc-button primary" id="navqc-reconcile" ${readiness.status === "ready" ? "" : "disabled"}>Approve & run NAV reconciliation</button><button class="navqc-button secondary" id="navqc-refresh">Refresh readiness</button></div></div>`;
  }

  function reconciliationView(result) {
    const review = result.review || {};
    const findings = review.findings || [];
    return `<div class="navqc-panel"><h3>NAV reconciliation</h3><p>The existing deterministic NAV Quality Controller performed the financial checks.</p>
      <div class="navqc-banner"><div><span class="eyebrow">Deterministic action</span><strong>${esc((review.action || "review").replaceAll("_", " "))}</strong></div>
      <div class="navqc-metrics"><div><span>Controls passed</span><strong>${esc(review.controls_passed ?? 0)}</strong></div><div><span>Exceptions</span><strong>${esc(review.exceptions_open ?? findings.length)}</strong></div><div><span>Round</span><strong>${esc(result.iteration?.round_number ?? 1)}</strong></div></div></div>
      <div>${findings.map((finding) => `<article class="navqc-finding"><header><strong>${esc(finding.title || finding.code)}</strong>${pill(finding.severity)}</header><p>${esc(finding.detail)}</p>${finding.expected != null ? `<p><strong>Expected:</strong> ${esc(finding.expected)} · <strong>Observed:</strong> ${esc(finding.observed)}</p>` : ""}</article>`).join("") || '<div class="navqc-empty">No NAV exceptions were returned.</div>'}</div>
      <div class="navqc-boundary">${esc(result.financial_boundary || "This workflow does not amend the official NAV.")}</div>
      <div class="navqc-actions"><button class="navqc-button primary" id="navqc-review">Continue to NAV review</button><button class="navqc-button secondary" id="navqc-history">View review history</button></div></div>`;
  }

  function reviewView(review) {
    const items = review.investigations || [];
    return `<div class="navqc-panel"><h3>Agentic NAV review</h3><p>${esc(review.agent_summary || "The Fund Manager investigation agent reviewed the deterministic NAV findings.")}</p>
      ${items.map((item) => `<article class="navqc-finding"><header><strong>${esc(item.issue_id || "NAV finding")}</strong>${pill(item.priority)}</header><p>${esc(item.finding)}</p>${item.likely_cause ? `<p><strong>Likely cause:</strong> ${esc(item.likely_cause)}</p>` : ""}${item.evidence_gap ? `<p><strong>Evidence gap:</strong> ${esc(item.evidence_gap)}</p>` : ""}<p><strong>Recommended action:</strong> ${esc(item.recommended_action)}</p></article>`).join("") || '<div class="navqc-empty">No additional agent findings were required.</div>'}
      <div class="navqc-boundary">${esc(review.control_boundary)}</div>
      ${decisionForm(review.recommended_human_action)}</div>`;
  }

  function decisionForm(recommendation) {
    return `<div class="navqc-decision"><p>Agent recommendation: <strong>${esc(String(recommendation || "review").replaceAll("_", " "))}</strong></p>
      <input id="navqc-note" type="text" placeholder="Optional Fund Manager decision note">
      <div class="navqc-actions"><button class="navqc-button primary" data-nav-decision="approve_nav">Approve NAV</button><button class="navqc-button secondary" data-nav-decision="approve_with_exception">Approve with exception</button><button class="navqc-button secondary" data-nav-decision="request_evidence">Request evidence</button><button class="navqc-button secondary" data-nav-decision="return_to_administrator">Return to administrator</button><button class="navqc-button danger" data-nav-decision="escalate">Escalate</button></div></div>`;
  }

  function decidedView(decision) {
    return `<div class="navqc-panel"><h3>NAV decision recorded</h3><div class="navqc-banner"><div><span class="eyebrow">Fund Manager action</span><strong>${esc(String(decision.action || "recorded").replaceAll("_", " "))}</strong></div></div>${decision.note ? `<p>${esc(decision.note)}</p>` : ""}
      <div class="navqc-actions"><button class="navqc-button primary" id="navqc-history">View NAV review history</button></div><div class="navqc-boundary">${esc(decision.financial_boundary)}</div></div>`;
  }

  function historyView() {
    if (!state.history) return "";
    if (!state.history.available) return `<div class="navqc-panel"><h3>Review history</h3><div class="navqc-empty">${esc(state.history.reason)}</div></div>`;
    const history = state.history.history || {};
    const rounds = history.rounds || history.iterations || [];
    return `<div class="navqc-panel"><h3>Review history</h3><p>${esc(history.legal_entity || "Fund")} · ${esc(history.period_end || "")}</p><div class="navqc-history">${rounds.map((round) => `<div class="navqc-round"><span>Round ${esc(round.round_number)}</span><strong>${esc(String(round.action || "review").replaceAll("_", " "))}</strong><span>${esc(round.exceptions_open ?? 0)} exceptions</span></div>`).join("") || '<div class="navqc-empty">History is recorded but no round details were returned.</div>'}</div></div>`;
  }

  function render() {
    const root = document.querySelector("#navqc-content");
    if (!root) return;
    const nav = workflow();
    let body;
    if (!state.caseData) body = noCase();
    else if (!nav.readiness) body = evidence();
    else if (!nav.reconciliation) body = readinessView(nav.readiness);
    else if (!nav.review) body = reconciliationView(nav.reconciliation);
    else if (!nav.decision) body = reviewView(nav.review);
    else body = decidedView(nav.decision);
    root.innerHTML = `${header()}${stepper()}${body}${historyView()}`;
    bind();
  }

  async function run(path, options = { method: "POST" }) {
    if (state.busy || !state.caseData) return;
    state.busy = true;
    try {
      const payload = await api(path, options);
      rememberCase(payload);
    } catch (error) {
      notify(error.message || "NAV Quality Controller step failed.", true);
    } finally {
      state.busy = false;
    }
  }

  async function loadHistory() {
    if (!state.caseData) return;
    try {
      state.history = await api(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/history`);
      render();
    } catch (error) { notify(error.message || "Could not load NAV history.", true); }
  }

  function bind() {
    const id = state.caseData?.case_id;
    document.querySelector("#navqc-readiness")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-refresh")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-reconcile")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/reconcile`));
    document.querySelector("#navqc-review")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/review`));
    document.querySelector("#navqc-history")?.addEventListener("click", loadHistory);
    document.querySelectorAll("[data-nav-decision]").forEach((button) => button.addEventListener("click", () => {
      const note = document.querySelector("#navqc-note")?.value || null;
      run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: button.dataset.navDecision, note }),
      });
    }));
  }

  async function restore() {
    const caseId = localStorage.getItem(CASE_KEY);
    if (!caseId) return;
    try {
      const payload = await api(`/api/fund-manager/cases/${encodeURIComponent(caseId)}`);
      rememberCase(payload);
    } catch {
      localStorage.removeItem(CASE_KEY);
    }
  }

  injectStyles();
  document.addEventListener("DOMContentLoaded", async () => {
    mount();
    await restore();
  });
})();
