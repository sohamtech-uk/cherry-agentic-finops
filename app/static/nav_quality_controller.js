(() => {
  "use strict";

  const state = { caseData: null, history: null, busy: false };
  const nativeFetch = window.fetch.bind(window);
  const CASE_KEY = "cherry_fund_manager_case_id";
  const esc = (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const workflow = () => state.caseData?.workflows?.nav_quality_controller || {};
  const notify = (m, e = false) => typeof toast === "function" ? toast(m, e) : e && console.error(m);

  function rememberCase(payload) {
    if (!payload?.case_id) return;
    state.caseData = payload;
    localStorage.setItem(CASE_KEY, payload.case_id);
    render();
  }

  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const url = String(args[0] instanceof Request ? args[0].url : args[0]);
    if (url.includes("/api/fund-manager/cases")) {
      try {
        const payload = await response.clone().json();
        if (payload?.case_id && payload?.classification) rememberCase(payload);
      } catch { /* non-case response */ }
    }
    return response;
  };

  async function api(path, options = {}) {
    const response = await nativeFetch(path, options);
    let payload = {};
    try { payload = await response.json(); } catch { /* empty response */ }
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
    const anchor = document.querySelector("#fund-manager") || document.querySelector(".source-strip");
    if (!anchor) return;
    anchor.insertAdjacentHTML("afterend", `<section class="navqc-shell" id="nav-quality-controller"><div class="navqc-nav"><a href="#fund-manager">General Control Review</a><a class="active" href="#nav-quality-controller">NAV Quality Controller</a></div><div class="navqc-card"><div id="navqc-content"></div></div></section>`);
    render();
  }

  function pill(status) {
    const value = String(status || "review");
    return `<span class="navqc-pill ${esc(value)}">${esc(value.replaceAll("_", " "))}</span>`;
  }

  function header() {
    return `<div class="navqc-head"><div><p class="eyebrow">Fund Manager · specialist workflow</p><h2>NAV Quality Controller</h2><p>Upload evidence, reconcile NAV, resolve each exception, then continue to consolidated review.</p></div><span class="navqc-case">${state.caseData ? `Case ${esc(state.caseData.case_id)}` : "No active Fund Manager case"}</span></div>`;
  }

  function stepper() {
    const nav = workflow();
    const active = nav.decision ? 5 : nav.review ? 4 : nav.reconciliation ? 3 : nav.readiness ? 2 : state.caseData ? 1 : 0;
    return `<div class="navqc-stepper">${["Evidence", "NAV readiness", "Reconciliation", "NAV review", "Decision", "History"].map((label, i) => `<div class="navqc-step ${i + 1 < active ? "done" : i + 1 === active ? "active" : ""}"><span>${i + 1}</span><strong>${label}</strong></div>`).join("")}</div>`;
  }

  function noCase() {
    return `<div class="navqc-panel"><h3>Upload evidence first</h3><div class="navqc-empty">NAV Quality Controller becomes available after files are uploaded and classified.</div><div class="navqc-actions"><a class="navqc-button primary" href="#fund-manager">Upload files</a></div></div>`;
  }

  function evidence() {
    const sources = state.caseData?.classification?.sources || [];
    const relevant = sources.filter((s) => ["nav_workbook", "investor_gl", "side_letter", "lpa"].includes(s.detected_type));
    return `<div class="navqc-panel"><h3>Shared case evidence</h3><div class="navqc-grid">${relevant.map((s) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(s.filename)}</strong>${pill(s.validation_status === "accepted" ? "ready" : "review")}</div><p>${esc(s.detected_type)}</p></div>`).join("") || '<div class="navqc-empty">No NAV-specific evidence identified yet.</div>'}</div><div class="navqc-actions"><button class="navqc-button primary" id="navqc-readiness">Assess NAV readiness</button><a class="navqc-button secondary" href="#fund-manager">Upload / replace evidence</a></div></div>`;
  }

  function readinessView(readiness) {
    const inputs = readiness.inputs || {};
    const rows = [["Administrator NAV summary", inputs.nav_summary], ["Investor-level GL", inputs.source_ledger], ["Structured side-letter rules", inputs.side_letter_rules]];
    return `<div class="navqc-panel"><h3>NAV readiness</h3><p>Missing or updated evidence can be supplied before reconciliation.</p><div class="navqc-grid">${rows.map(([label, item]) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(label)}</strong>${pill(item ? "ready" : "optional_evidence")}</div><p>${item ? esc(item.filename) : "Not supplied / not identified"}</p></div>`).join("")}</div>${(readiness.blockers || []).map((x) => `<div class="navqc-blocker">${esc(x)}</div>`).join("")}<div class="navqc-actions"><button class="navqc-button primary" id="navqc-reconcile" ${readiness.status === "ready" ? "" : "disabled"}>Run NAV reconciliation</button><a class="navqc-button secondary" href="#fund-manager">Upload missing / updated file</a><button class="navqc-button secondary" id="navqc-refresh">Refresh readiness</button></div></div>`;
  }

  function exceptionKey(finding, index) {
    return String(finding.code || finding.issue_id || finding.title || `exception-${index + 1}`).replace(/[^a-zA-Z0-9_.-]/g, "-").slice(0, 120);
  }

  function exceptionCard(finding, index) {
    const key = exceptionKey(finding, index);
    const resolution = workflow().exception_resolutions?.[key];
    const resolved = resolution?.status === "ignored";
    return `<article class="navqc-finding" data-exception="${esc(key)}"><header><strong>${esc(finding.title || finding.code || `Exception ${index + 1}`)}</strong>${pill(resolved ? "ignored" : finding.severity)}</header><p>${esc(finding.detail)}</p>${finding.expected != null ? `<p><strong>Expected:</strong> ${esc(finding.expected)} · <strong>Observed:</strong> ${esc(finding.observed)}</p>` : ""}${resolution ? `<div class="navqc-boundary"><strong>${esc(resolution.status.replaceAll("_", " "))}</strong>${resolution.filename ? ` · ${esc(resolution.filename)}` : ""}${resolution.reason ? ` · ${esc(resolution.reason)}` : ""}</div>` : ""}<div class="navqc-actions"><button class="navqc-button primary" data-upload-exception="${esc(key)}">Upload file</button><input type="file" hidden data-exception-file="${esc(key)}"><button class="navqc-button secondary" data-ignore-exception="${esc(key)}" ${resolved ? "disabled" : ""}>Ignore</button><button class="navqc-button secondary" data-details-exception="${esc(key)}">View details</button></div><div class="navqc-boundary" data-exception-details="${esc(key)}" hidden>Upload supporting evidence to re-classify the case and re-run NAV readiness. Ignoring requires a reason and remains in the audit trail.</div></article>`;
  }

  function reconciliationView(result) {
    const review = result.review || {};
    const findings = review.findings || [];
    return `<div class="navqc-panel"><h3>NAV reconciliation</h3><div class="navqc-metrics"><div><span>Controls passed</span><strong>${esc(review.controls_passed ?? 0)}</strong></div><div><span>Exceptions</span><strong>${esc(review.exceptions_open ?? findings.length)}</strong></div><div><span>Actual round</span><strong>${esc(result.iteration?.round_number ?? 1)}</strong></div></div><p>Resolve each exception by uploading supporting evidence or explicitly ignoring it.</p><div>${findings.map(exceptionCard).join("") || '<div class="navqc-empty">No NAV exceptions were returned.</div>'}</div><div class="navqc-actions"><button class="navqc-button primary" id="navqc-review">Build consolidated NAV review</button><button class="navqc-button secondary" id="navqc-history">View review history</button></div></div>`;
  }

  function reviewView(review) {
    const items = review.investigations || [];
    return `<div class="navqc-panel"><h3>Agentic NAV review</h3><p>${esc(review.agent_summary || "The Fund Manager investigation agent reviewed the deterministic findings.")}</p>${items.map((i) => `<article class="navqc-finding"><header><strong>${esc(i.issue_id || "NAV finding")}</strong>${pill(i.priority)}</header><p>${esc(i.finding)}</p>${i.evidence_gap ? `<p><strong>Evidence gap:</strong> ${esc(i.evidence_gap)}</p>` : ""}<p><strong>Recommended action:</strong> ${esc(i.recommended_action)}</p></article>`).join("")}${decisionForm(review.recommended_human_action)}</div>`;
  }

  function decisionForm(recommendation) {
    return `<div class="navqc-decision"><p>Agent recommendation: <strong>${esc(String(recommendation || "review").replaceAll("_", " "))}</strong></p><input id="navqc-note" type="text" placeholder="Optional Fund Manager decision note"><div class="navqc-actions"><button class="navqc-button primary" data-nav-decision="approve_nav">Approve NAV</button><button class="navqc-button secondary" data-nav-decision="approve_with_exception">Approve with exception</button><button class="navqc-button secondary" data-nav-decision="request_evidence">Request evidence</button><button class="navqc-button danger" data-nav-decision="escalate">Escalate</button></div></div>`;
  }

  function decidedView(decision) {
    return `<div class="navqc-panel"><h3>NAV decision recorded</h3><p><strong>${esc(String(decision.action || "recorded").replaceAll("_", " "))}</strong></p>${decision.note ? `<p>${esc(decision.note)}</p>` : ""}<button class="navqc-button primary" id="navqc-history">View NAV review history</button></div>`;
  }

  function historyView() {
    if (!state.history) return "";
    if (!state.history.available) return `<div class="navqc-panel"><h3>Review history</h3><div class="navqc-empty">${esc(state.history.reason)}</div></div>`;
    const history = state.history.history || {};
    const rounds = history.history || history.rounds || history.iterations || [];
    return `<div class="navqc-panel"><h3>Review history</h3><div class="navqc-history">${rounds.map((r) => `<div class="navqc-round"><span>Round ${esc(r.round_number)}</span><strong>${esc(String(r.action || "review").replaceAll("_", " "))}</strong><span>${esc(r.exceptions_open ?? 0)} exceptions</span></div>`).join("")}</div></div>`;
  }

  function render() {
    const root = document.querySelector("#navqc-content");
    if (!root) return;
    const nav = workflow();
    const body = !state.caseData ? noCase() : !nav.readiness ? evidence() : !nav.reconciliation ? readinessView(nav.readiness) : !nav.review ? reconciliationView(nav.reconciliation) : !nav.decision ? reviewView(nav.review) : decidedView(nav.decision);
    root.innerHTML = `${header()}${stepper()}${body}${historyView()}`;
    bind();
  }

  async function run(path, options = { method: "POST" }) {
    if (state.busy || !state.caseData) return;
    state.busy = true;
    try { rememberCase(await api(path, options)); } catch (e) { notify(e.message || "NAV workflow step failed.", true); } finally { state.busy = false; }
  }

  async function uploadEvidence(key, file) {
    if (!file || state.busy) return;
    const form = new FormData();
    form.append("file", file);
    await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/evidence`, { method: "POST", body: form });
    notify("Evidence uploaded. NAV readiness has been refreshed; re-run reconciliation when ready.");
  }

  async function ignoreException(key) {
    const reason = window.prompt("Reason for ignoring this exception (required):");
    if (!reason?.trim()) return;
    const note = window.prompt("Optional supporting note:") || null;
    await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/ignore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason.trim(), note }) });
    notify("Exception ignored with an auditable reason.");
  }

  async function loadHistory() {
    try { state.history = await api(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/history`); render(); } catch (e) { notify(e.message, true); }
  }

  function bind() {
    const id = state.caseData?.case_id;
    document.querySelector("#navqc-readiness")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-refresh")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-reconcile")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/reconcile`));
    document.querySelector("#navqc-review")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/review`));
    document.querySelector("#navqc-history")?.addEventListener("click", loadHistory);
    document.querySelectorAll("[data-upload-exception]").forEach((b) => b.addEventListener("click", () => document.querySelector(`[data-exception-file="${CSS.escape(b.dataset.uploadException)}"]`)?.click()));
    document.querySelectorAll("[data-exception-file]").forEach((i) => i.addEventListener("change", () => uploadEvidence(i.dataset.exceptionFile, i.files?.[0])));
    document.querySelectorAll("[data-ignore-exception]").forEach((b) => b.addEventListener("click", () => ignoreException(b.dataset.ignoreException)));
    document.querySelectorAll("[data-details-exception]").forEach((b) => b.addEventListener("click", () => { const el = document.querySelector(`[data-exception-details="${CSS.escape(b.dataset.detailsException)}"]`); if (el) el.hidden = !el.hidden; }));
    document.querySelectorAll("[data-nav-decision]").forEach((b) => b.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: b.dataset.navDecision, note: document.querySelector("#navqc-note")?.value || null }) })));
  }

  async function restore() {
    const id = localStorage.getItem(CASE_KEY);
    if (!id) return;
    try { rememberCase(await api(`/api/fund-manager/cases/${encodeURIComponent(id)}`)); } catch { localStorage.removeItem(CASE_KEY); }
  }

  injectStyles();
  document.addEventListener("DOMContentLoaded", async () => { mount(); await restore(); });
})();
