(() => {
  "use strict";

  const REQUEST_COOLDOWN_MS = 5000;
  const state = { files: [], caseData: null, busy: false, lastRequestAt: new Map() };

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

  const STEPS = [
    ["classified", "Evidence"], ["planned", "Control plan"], ["executed", "Controls"],
    ["investigated", "Investigation"], ["decided", "Decision"],
  ];

  const q = (selector, root = document) => root.querySelector(selector);
  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function notify(message, error = false) {
    if (typeof toast === "function") return toast(message, error);
    if (error) console.error(message);
  }

  function busy(value) {
    state.busy = value;
    if (typeof loading === "function") loading(value);
    render();
  }

  function injectStyles() {
    if (q('link[href="/static/fund_manager.css"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet"; link.href = "/static/fund_manager.css"; document.head.appendChild(link);
  }

  function shellMarkup() {
    return `<section class="fm-shell" id="fund-manager" aria-labelledby="fm-title"><div class="fm-inner">
      <div class="fm-head"><p class="fm-kicker">Cherry Fund Manager · guided control review</p>
      <h2 id="fm-title">Review evidence step by step.<br><em>You choose when Cherry proceeds.</em></h2>
      <p>Upload mixed fund evidence, review classification first, then explicitly continue through agentic control planning, deterministic execution, exception investigation and the final human decision.</p></div>
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

  function renderStepper() {
    const target = q("#fm-stepper"); if (!target) return;
    const active = currentIndex();
    target.innerHTML = `<div class="fm-stepper">${STEPS.map(([, label], index) => {
      const cls = index < active ? "done" : index === active ? "active" : "";
      return `<div class="fm-step ${cls}"><span>${index + 1}</span><strong>${esc(label)}</strong></div>`;
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
    const now = Date.now(); const last = state.lastRequestAt.get(path) || 0;
    const remaining = REQUEST_COOLDOWN_MS - (now - last);
    if (remaining > 0) throw new Error(`Please wait ${Math.ceil(remaining / 1000)} seconds before retrying.`);
    state.lastRequestAt.set(path, now);
    const response = await fetch(path, options);
    let body = {}; try { body = await response.json(); } catch { body = {}; }
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `${response.status} ${response.statusText}`);
    return body;
  }

  async function runAction(action) {
    if (state.busy) return; busy(true);
    try { state.caseData = await action(); render(); }
    catch (error) { notify(error.message || "Fund Manager step failed.", true); }
    finally { busy(false); }
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
    if (["ready", "executed", "completed", "info"].includes(status)) return `<span class="fm-pill ok">${esc(status)}</span>`;
    if (["failed", "high"].includes(status)) return `<span class="fm-pill error">${esc(status)}</span>`;
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
      <p>${esc(issue.summary)}</p><p class="fm-issue-action"><strong>Recommended action:</strong> ${esc(issue.recommended_action)}</p>
    </div>`).join("")}</div>`;
  }

  function renderUpload() {
    const fileRows = state.files.map((file, index) => `<div class="fm-file-row">
      <span class="fm-file-name">${esc(file.name)}</span><span class="fm-file-size">${esc(humanSize(file.size))}</span>
      <button type="button" data-remove-file="${index}" aria-label="Remove ${esc(file.name)}">✕</button></div>`).join("");
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 1</span><h3>Upload and classify evidence</h3><p>No financial control runs at this stage.</p></div>
      <div class="fm-dropzone" id="fm-dropzone"><strong>Drop evidence here</strong><span>PDF · XLSX · CSV · JSON</span>
      <button type="button" class="fm-button secondary" id="fm-browse">Browse files</button>
      <input type="file" id="fm-file-input" multiple accept=".pdf,.xlsx,.xls,.csv,.json,.txt"></div>
      <div class="fm-file-list">${fileRows}</div><div class="fm-actions">
      <button type="button" class="fm-button primary" id="fm-classify" ${state.files.length && !state.busy ? "" : "disabled"}>Upload & classify</button>
      ${state.files.length ? '<button type="button" class="fm-button ghost" id="fm-clear">Clear</button>' : ""}
      <span class="fm-file-count">${state.files.length ? `${state.files.length} selected` : ""}</span></div>`;
  }

  function renderClassified() {
    const report = state.caseData.classification;
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 1 complete</span><h3>Evidence classification report</h3>
      <p>Case <code>${esc(state.caseData.case_id)}</code> is stored for this guided review.</p></div>
      <div class="fm-inventory-head"><h3>Evidence inventory</h3><span>${esc(report.accepted_count)} accepted · ${esc(report.rejected_count)} review</span></div>
      <div class="fm-source-grid">${(report.sources || []).map(sourceCard).join("")}</div>
      <div class="fm-boundary">Classification only identifies the evidence. No control has run and no pass/fail decision has been made.</div>
      <div class="fm-checkpoint"><strong>Proceed to agentic control planning?</strong><p>The planning agent will select applicable controls, but it will not execute them.</p>
      <button type="button" class="fm-button primary" id="fm-plan">Continue to control planning</button></div>`;
  }

  function renderPlanned() {
    const plan = state.caseData.plan;
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 2</span><h3>Agent control plan</h3>
      <p>${esc(plan?.agent_summary || "The agent selected the controls supported by the accepted evidence.")}</p></div>
      <div class="fm-plan-grid">${planRows(plan) || '<div class="fm-empty">No applicable controls were planned.</div>'}</div>
      <div class="fm-boundary">Planning is advisory only. Controls marked ready have not run yet; awaiting-evidence and adapter-pending controls cannot silently pass.</div>
      <div class="fm-checkpoint"><strong>Approve execution of the ready controls?</strong><p>Only controls marked <em>ready</em> will be sent to deterministic financial tools.</p>
      <button type="button" class="fm-button primary" id="fm-execute">Approve & run controls</button></div>`;
  }

  function renderExecuted() {
    const execution = state.caseData.execution;
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 3</span><h3>Deterministic control results</h3>
      <p>${esc(execution?.agent_summary || "Approved controls have completed.")}</p></div>
      <div class="fm-qc-banner ${execution?.status === "clean" ? "ok" : "review"}"><div><span class="fm-kicker">Execution status</span>
      <strong>${esc((execution?.status || "completed").replaceAll("_", " "))}</strong></div><div class="fm-qc-metrics">
      <div><span>Issues</span><strong>${esc(execution?.issues_found || 0)}</strong></div><div><span>Material</span><strong>${esc(execution?.material || 0)}</strong></div>
      <div><span>Critical</span><strong>${esc(execution?.critical || 0)}</strong></div></div></div>${issueCards(execution)}
      <details class="fm-control-plan" open><summary>Executed control plan</summary><div class="fm-plan-grid">${planRows(execution)}</div></details>
      <div class="fm-boundary">The agent chose which approved controls to invoke; deterministic tools produced the financial calculations and comparisons.</div>
      <div class="fm-checkpoint"><strong>Continue to exception investigation?</strong><p>The investigation agent can explain and prioritise results but cannot change them.</p>
      <button type="button" class="fm-button primary" id="fm-investigate">Investigate results</button>
      <button type="button" class="fm-button secondary" id="fm-skip-investigation">Go to decision</button></div>`;
  }

  function renderInvestigated() {
    const investigation = state.caseData.investigation;
    const rows = (investigation?.investigations || []).map((item) => `<div class="fm-issue-card">
      <div class="fm-issue-head"><strong>${esc(item.issue_id || "Finding")}</strong>${statusPill(item.priority)}</div>
      <p>${esc(item.finding)}</p>${item.likely_cause ? `<p><strong>Likely cause:</strong> ${esc(item.likely_cause)}</p>` : ""}
      ${item.evidence_gap ? `<p><strong>Evidence gap:</strong> ${esc(item.evidence_gap)}</p>` : ""}
      <p class="fm-issue-action"><strong>Recommended action:</strong> ${esc(item.recommended_action)}</p></div>`).join("");
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 4</span><h3>Agent investigation</h3>
      <p>${esc(investigation?.agent_summary || "The agent reviewed the deterministic results.")}</p></div>
      <div class="fm-issue-grid">${rows || '<div class="fm-empty">No additional investigation findings.</div>'}</div>
      <div class="fm-boundary">Investigation explains and prioritises deterministic results; it does not rewrite control outcomes.</div>
      <div class="fm-checkpoint"><strong>Proceed to human decision?</strong><p>Recommended next action: <strong>${esc((investigation?.recommended_human_action || "review").replaceAll("_", " "))}</strong></p>
      <button type="button" class="fm-button primary" id="fm-decision-step">Continue to decision</button></div>`;
  }

  function decisionMarkup() {
    const recommendation = state.caseData.investigation?.recommended_human_action || "review_missing_evidence";
    return `<div class="fm-stage-head"><span class="fm-kicker">Step 5</span><h3>Human decision</h3>
      <p>Review the evidence, control results and agent recommendation before recording the case action.</p></div>
      <div class="fm-decision-card"><p>Agent recommendation: <strong>${esc(recommendation.replaceAll("_", " "))}</strong></p>
      <label class="fm-field"><span>Decision note</span><input id="fm-decision-note" type="text" placeholder="Optional rationale or follow-up note"></label>
      <div class="fm-actions"><button class="fm-button primary" data-decision="accept_and_close">Accept & close</button>
      <button class="fm-button secondary" data-decision="request_evidence">Request evidence</button>
      <button class="fm-button secondary" data-decision="assign_and_monitor">Assign for review</button>
      <button class="fm-button danger" data-decision="escalate_immediately">Escalate</button></div></div>`;
  }

  function renderDecided() {
    const decision = state.caseData.decision;
    return `<div class="fm-stage-head"><span class="fm-kicker">Review complete</span><h3>Decision recorded</h3>
      <p>Case <code>${esc(state.caseData.case_id)}</code></p></div><div class="fm-qc-banner ok"><div><span class="fm-kicker">Human action</span>
      <strong>${esc((decision?.action || "recorded").replaceAll("_", " "))}</strong></div></div>
      ${decision?.note ? `<div class="fm-boundary"><strong>Note:</strong> ${esc(decision.note)}</div>` : ""}
      <div class="fm-actions"><button type="button" class="fm-button secondary" id="fm-new-case">Start another review</button></div>`;
  }

  function render() {
    renderStepper(); const target = q("#fm-stage"); if (!target) return;
    if (!state.caseData) target.innerHTML = renderUpload();
    else if (state.caseData.stage === "classified") target.innerHTML = renderClassified();
    else if (state.caseData.stage === "planned") target.innerHTML = renderPlanned();
    else if (state.caseData.stage === "executed" && !state.caseData.showDecision) target.innerHTML = renderExecuted();
    else if (state.caseData.stage === "investigated" && !state.caseData.showDecision) target.innerHTML = renderInvestigated();
    else if (["executed", "investigated"].includes(state.caseData.stage)) target.innerHTML = decisionMarkup();
    else target.innerHTML = renderDecided();
  }

  function addFiles(fileList) {
    const keys = new Set(state.files.map((file) => `${file.name}:${file.size}`));
    for (const file of [...fileList]) { const key = `${file.name}:${file.size}`; if (!keys.has(key)) { state.files.push(file); keys.add(key); } }
    render();
  }

  function reset() { state.files = []; state.caseData = null; state.lastRequestAt.clear(); render(); }

  function wireEvents() {
    q("#fm-stage")?.addEventListener("click", (event) => {
      const target = event.target.closest("button"); if (!target) return;
      if (target.id === "fm-browse") q("#fm-file-input")?.click();
      if (target.id === "fm-clear" || target.id === "fm-new-case") reset();
      if (target.dataset.removeFile !== undefined) { state.files.splice(Number(target.dataset.removeFile), 1); render(); }
      if (target.id === "fm-classify") runAction(() => request("/api/fund-manager/cases", { method: "POST", body: buildEvidenceForm() }));
      if (target.id === "fm-plan") runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/plan`, { method: "POST" }));
      if (target.id === "fm-execute") runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/execute`, { method: "POST" }));
      if (target.id === "fm-investigate") runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/investigate`, { method: "POST" }));
      if (target.id === "fm-skip-investigation" || target.id === "fm-decision-step") { state.caseData.showDecision = true; render(); }
      if (target.dataset.decision) {
        const note = q("#fm-decision-note")?.value || null;
        runAction(() => request(`/api/fund-manager/cases/${state.caseData.case_id}/decision`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: target.dataset.decision, note }),
        }));
      }
    });
    q("#fm-stage")?.addEventListener("change", (event) => {
      if (event.target.id === "fm-file-input") { addFiles(event.target.files); event.target.value = ""; }
    });
    q("#fm-stage")?.addEventListener("dragover", (event) => {
      const dropzone = event.target.closest("#fm-dropzone"); if (!dropzone) return;
      event.preventDefault(); dropzone.classList.add("dragover");
    });
    q("#fm-stage")?.addEventListener("dragleave", (event) => {
      const dropzone = event.target.closest("#fm-dropzone"); if (dropzone) dropzone.classList.remove("dragover");
    });
    q("#fm-stage")?.addEventListener("drop", (event) => {
      const dropzone = event.target.closest("#fm-dropzone"); if (!dropzone) return;
      event.preventDefault(); dropzone.classList.remove("dragover");
      if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
    });
  }

  function addNavLink() {
    const nav = q(".primary-nav"); if (!nav || q('a[href="#fund-manager"]', nav)) return;
    nav.insertAdjacentHTML("afterbegin", '<a href="#fund-manager"><strong>Fund Manager</strong></a>');
  }

  function init() { injectStyles(); mountShell(); addNavLink(); wireEvents(); render(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
