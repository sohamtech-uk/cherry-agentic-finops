(() => {
  "use strict";

  const state = { caseData: null, history: null, busy: false };
  const CASE_KEY = "cherry_fund_manager_case_id";
  const esc = (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const workflow = () => state.caseData?.workflows?.nav_quality_controller || {};
  const notify = (m, e = false) => typeof toast === "function" ? toast(m, e) : e && console.error(m);

  function rememberCase(payload, { broadcast = true } = {}) {
    if (!payload?.case_id) return;
    state.caseData = payload;
    localStorage.setItem(CASE_KEY, payload.case_id);
    render();
    if (broadcast) window.dispatchEvent(new CustomEvent("fund-manager-case-updated", { detail: payload }));
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
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
    const anchor = document.querySelector("#fund-manager") || document.querySelector(".source-strip");
    if (!anchor) return;
    anchor.insertAdjacentHTML("afterend", `<section class="navqc-shell" id="nav-quality-controller" hidden><div class="navqc-card"><div id="navqc-content"></div></div></section>`);
    render();
    if (localStorage.getItem("cherry_fund_manager_active_tab") === "nav" && state.caseData && typeof window.setFundManagerTab === "function") window.setFundManagerTab("nav");
  }

  function pill(status) {
    const value = String(status || "review");
    return `<span class="navqc-pill ${esc(value)}">${esc(value.replaceAll("_", " "))}</span>`;
  }

  function header() {
    return `<div class="navqc-head"><div><p class="eyebrow">Fund Manager · specialist workflow</p><h2>NAV Quality Controller</h2>
      <p>This tab reuses the evidence already uploaded to the case. Add only new evidence when a gap or exception requires it.</p></div>
      <span class="navqc-case">${state.caseData ? `Case ${esc(state.caseData.case_id)}` : "No active Fund Manager case"}</span></div>`;
  }

  function stepper() {
    const nav = workflow();
    const active = nav.decision ? 5 : nav.review ? 4 : nav.reconciliation ? 3 : nav.readiness ? 2 : state.caseData ? 1 : 0;
    return `<div class="navqc-stepper">${["Evidence", "NAV readiness", "Reconciliation", "NAV review", "Decision", "History"].map((label, i) =>
      `<div class="navqc-step ${i + 1 < active ? "done" : i + 1 === active ? "active" : ""}"><span>${i + 1}</span><strong>${label}</strong></div>`).join("")}</div>`;
  }

  function noCase() {
    return `<div class="navqc-panel"><h3>Upload evidence first</h3><div class="navqc-empty">Create the case from General Document Review. The same files will then be available here without another upload.</div>
      <div class="navqc-actions"><button class="navqc-button primary" data-open-general>Go to General Document Review</button></div></div>`;
  }

  function evidence() {
    const sources = state.caseData?.classification?.sources || [];
    const relevant = sources.filter((s) => ["nav_workbook", "investor_gl", "side_letter", "lpa"].includes(s.detected_type));
    return `<div class="navqc-panel"><h3>Shared case evidence</h3><p>These files were uploaded once to the case and are reused by NAV Quality Controller.</p>
      <div class="navqc-grid">${relevant.map((s) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(s.filename)}</strong>${pill(s.validation_status === "accepted" ? "ready" : "review")}</div><p>${esc(s.detected_type)}</p></div>`).join("") || '<div class="navqc-empty">No NAV-specific evidence identified yet.</div>'}</div>
      <div class="navqc-actions"><button class="navqc-button primary" id="navqc-readiness">Assess NAV readiness</button><button class="navqc-button secondary" data-open-general>Add new evidence</button></div></div>`;
  }

  function readinessView(readiness) {
    const inputs = readiness.inputs || {};
    const rows = [["Administrator NAV summary", inputs.nav_summary], ["Investor-level GL", inputs.source_ledger], ["Structured side-letter rules", inputs.side_letter_rules]];
    return `<div class="navqc-panel"><h3>NAV readiness</h3><p>Missing or updated evidence can be added to this same case; previously uploaded files are not resubmitted.</p>
      <div class="navqc-grid">${rows.map(([label, item]) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(label)}</strong>${pill(item ? "ready" : "optional_evidence")}</div><p>${item ? esc(item.filename) : "Not supplied / not identified"}</p></div>`).join("")}</div>
      ${(readiness.blockers || []).map((x) => `<div class="navqc-blocker">${esc(x)}</div>`).join("")}
      <div class="navqc-actions"><button class="navqc-button primary" id="navqc-reconcile" ${readiness.status === "ready" ? "" : "disabled"}>Run NAV reconciliation</button>
      <button class="navqc-button secondary" data-open-general>Add missing / updated file</button><button class="navqc-button secondary" id="navqc-refresh">Refresh readiness</button></div></div>`;
  }

  function exceptionKey(finding, index) {
    return String(finding.code || finding.issue_id || finding.title || `exception-${index + 1}`).replace(/[^a-zA-Z0-9_.-]/g, "-").slice(0, 120);
  }

  function exceptionCard(finding, index) {
    const key = exceptionKey(finding, index);
    const resolution = workflow().exception_resolutions?.[key];
    const ignored = resolution?.status === "ignored";
    return `<article class="navqc-finding" data-exception="${esc(key)}"><header><strong>${esc(finding.title || finding.code || `Exception ${index + 1}`)}</strong>${pill(ignored ? "ignored" : finding.severity)}</header>
      <p>${esc(finding.detail)}</p>${finding.expected != null ? `<p><strong>Expected:</strong> ${esc(finding.expected)} · <strong>Observed:</strong> ${esc(finding.observed)}</p>` : ""}
      ${resolution ? `<div class="navqc-boundary"><strong>${esc(resolution.status.replaceAll("_", " "))}</strong>${resolution.filename ? ` · ${esc(resolution.filename)}` : ""}${resolution.reason ? ` · ${esc(resolution.reason)}` : ""}</div>` : ""}
      <div class="navqc-actions"><button class="navqc-button primary" data-upload-exception="${esc(key)}">Upload file</button><input type="file" hidden data-exception-file="${esc(key)}">
      <button class="navqc-button secondary" data-ignore-exception="${esc(key)}" ${ignored ? "disabled" : ""}>Ignore</button><button class="navqc-button secondary" data-details-exception="${esc(key)}">View details</button></div>
      <div class="navqc-boundary" data-exception-details="${esc(key)}" hidden>Upload only the new supporting file for this exception. It is appended to the current case; existing files are not sent again. Ignoring requires a reason and remains in the audit trail.</div></article>`;
  }

  function reconciliationView(result) {
    const review = result.review || {};
    const findings = review.findings || [];
    return `<div class="navqc-panel"><h3>NAV reconciliation</h3><div class="navqc-metrics"><div><span>Controls passed</span><strong>${esc(review.controls_passed ?? 0)}</strong></div>
      <div><span>Exceptions</span><strong>${esc(review.exceptions_open ?? findings.length)}</strong></div><div><span>Actual round</span><strong>${esc(result.iteration?.round_number ?? 1)}</strong></div></div>
      <p>Resolve each exception by uploading one new supporting file or explicitly ignoring it.</p><div>${findings.map(exceptionCard).join("") || '<div class="navqc-empty">No NAV exceptions were returned.</div>'}</div>
      <div class="navqc-actions"><button class="navqc-button primary" id="navqc-review">Build consolidated NAV review</button><button class="navqc-button secondary" id="navqc-history">View review history</button></div></div>`;
  }

  function reviewView(review) {
    const items = review.investigations || [];
    return `<div class="navqc-panel"><h3>Agentic NAV review</h3><p>${esc(review.agent_summary || "The Fund Manager investigation agent reviewed the deterministic findings.")}</p>
      ${items.map((i) => `<article class="navqc-finding"><header><strong>${esc(i.issue_id || "NAV finding")}</strong>${pill(i.priority)}</header><p>${esc(i.finding)}</p>${i.evidence_gap ? `<p><strong>Evidence gap:</strong> ${esc(i.evidence_gap)}</p>` : ""}<p><strong>Recommended action:</strong> ${esc(i.recommended_action)}</p></article>`).join("")}
      ${decisionForm(review.recommended_human_action)}</div>`;
  }

  function decisionForm(recommendation) {
    return `<div class="navqc-decision"><p>Agent recommendation: <strong>${esc(String(recommendation || "review").replaceAll("_", " "))}</strong></p>
      <input id="navqc-note" type="text" placeholder="Optional Fund Manager decision note"><div class="navqc-actions"><button class="navqc-button primary" data-nav-decision="approve_nav">Approve NAV</button>
      <button class="navqc-button secondary" data-nav-decision="approve_with_exception">Approve with exception</button><button class="navqc-button secondary" data-nav-decision="request_evidence">Request evidence</button>
      <button class="navqc-button danger" data-nav-decision="escalate">Escalate</button></div></div>`;
  }

  function decidedView(decision) {
    return `<div class="navqc-panel"><h3>NAV decision recorded</h3><p><strong>${esc(String(decision.action || "recorded").replaceAll("_", " "))}</strong></p>
      ${decision.note ? `<p>${esc(decision.note)}</p>` : ""}<button class="navqc-button primary" id="navqc-history">View NAV review history</button></div>`;
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
    try { rememberCase(await api(path, options)); }
    catch (e) { notify(e.message || "NAV workflow step failed.", true); }
    finally { state.busy = false; }
  }

  async function uploadEvidence(key, file) {
    if (!file || state.busy) return;
    const form = new FormData();
    form.append("file", file);
    await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/evidence`, { method: "POST", body: form });
    notify("New supporting evidence added to this case. Existing files were not resubmitted.");
  }

  async function ignoreException(key) {
    const reason = window.prompt("Reason for ignoring this exception (required):");
    if (!reason?.trim()) return;
    const note = window.prompt("Optional supporting note:") || null;
    await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/ignore`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason.trim(), note }),
    });
    notify("Exception ignored with an auditable reason.");
  }

  async function loadHistory() {
    try { state.history = await api(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/history`); render(); }
    catch (e) { notify(e.message, true); }
  }

  function bind() {
    const id = state.caseData?.case_id;
    document.querySelectorAll("[data-open-general]").forEach((b) => b.addEventListener("click", () => window.setFundManagerTab?.("general")));
    document.querySelector("#navqc-readiness")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-refresh")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-reconcile")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/reconcile`));
    document.querySelector("#navqc-review")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/review`));
    document.querySelector("#navqc-history")?.addEventListener("click", loadHistory);
    document.querySelectorAll("[data-upload-exception]").forEach((b) => b.addEventListener("click", () => document.querySelector(`[data-exception-file="${CSS.escape(b.dataset.uploadException)}"]`)?.click()));
    document.querySelectorAll("[data-exception-file]").forEach((i) => i.addEventListener("change", () => uploadEvidence(i.dataset.exceptionFile, i.files?.[0])));
    document.querySelectorAll("[data-ignore-exception]").forEach((b) => b.addEventListener("click", () => ignoreException(b.dataset.ignoreException)));
    document.querySelectorAll("[data-details-exception]").forEach((b) => b.addEventListener("click", () => {
      const el = document.querySelector(`[data-exception-details="${CSS.escape(b.dataset.detailsException)}"]`);
      if (el) el.hidden = !el.hidden;
    }));
    document.querySelectorAll("[data-nav-decision]").forEach((b) => b.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: b.dataset.navDecision, note: document.querySelector("#navqc-note")?.value || null }),
    })));
  }

  async function restore() {
    const id = localStorage.getItem(CASE_KEY);
    if (!id) return;
    try { rememberCase(await api(`/api/fund-manager/cases/${encodeURIComponent(id)}`), { broadcast: false }); }
    catch { localStorage.removeItem(CASE_KEY); }
  }

  window.addEventListener("fund-manager-case-updated", (event) => {
    if (event.detail?.case_id) rememberCase(event.detail, { broadcast: false });
  });
  window.addEventListener("fund-manager-case-cleared", () => {
    state.caseData = null;
    state.history = null;
    render();
  });
  window.addEventListener("fund-manager-nav-tab-opened", () => render());

  injectStyles();
  document.addEventListener("DOMContentLoaded", async () => {
    mount();
    await restore();
    if (localStorage.getItem("cherry_fund_manager_active_tab") === "nav" && state.caseData) window.setFundManagerTab?.("nav");
  });
})();
