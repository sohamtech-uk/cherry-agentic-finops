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
  const BUSY_STATES = {
    readiness: {
      kicker: "Readiness check in progress",
      title: "Checking NAV control readiness",
      copy: "Cherry is mapping the case evidence to the inputs required for NAV quality control before any reconciliation runs.",
      targetStep: 1,
      stages: [
        ["Evidence inventory", "done", "Using the evidence already stored in this case"],
        ["NAV input mapping", "active", "Locating the NAV summary, investor GL and rule evidence"],
        ["Readiness rules", "queued", "Confirm required inputs and surface blockers"],
        ["Reconciliation", "queued", "Runs only after readiness is confirmed"],
      ],
    },
    reconcile: {
      kicker: "Analysis in progress",
      title: "Running NAV reconciliation",
      copy: "Deterministic NAV controls are comparing the accepted evidence. Findings will appear only when the server returns the completed control result.",
      targetStep: 2,
      stages: [
        ["Evidence & rules", "done", "Readiness confirmed for this case"],
        ["NAV / fund controls", "active", "Footing, bridges and source comparisons are running"],
        ["Exception consolidation", "queued", "Breaks will be grouped after controls complete"],
        ["Review evidence", "queued", "Supporting evidence remains attached to returned findings"],
      ],
    },
    review: {
      kicker: "Review preparation in progress",
      title: "Consolidating NAV findings",
      copy: "Cherry is turning the completed reconciliation output into a focused exception review for the Fund Manager.",
      targetStep: 3,
      stages: [
        ["Reconciliation result", "done", "Completed control output retained"],
        ["Exception consolidation", "active", "Grouping related findings and evidence gaps"],
        ["Recommended actions", "queued", "Prepare review-ready next steps"],
        ["Human decision", "queued", "Decision authority remains with the Fund Manager"],
      ],
    },
    decision: {
      kicker: "Decision recording in progress",
      title: "Recording the Fund Manager decision",
      copy: "Cherry is writing the explicit human outcome to the case audit trail. It is not inferring approval or changing the official NAV.",
      targetStep: 4,
      stages: [
        ["Review pack", "done", "Findings and evidence reviewed"],
        ["Human instruction", "active", "Recording the selected decision and note"],
        ["Audit trail", "queued", "Persist the explicit decision on this case"],
      ],
    },
    evidence: {
      kicker: "Evidence update in progress",
      title: "Adding evidence to the case",
      copy: "Only the newly selected evidence is being added. Existing case evidence is not uploaded again.",
      targetStep: 0,
      stages: [
        ["New evidence", "active", "Upload and classify the selected file"],
        ["Case inventory", "queued", "Refresh recognised NAV evidence"],
        ["NAV readiness", "queued", "Recheck affected workflow inputs when requested"],
      ],
    },
    exception_evidence: {
      kicker: "Exception evidence in progress",
      title: "Attaching supporting evidence",
      copy: "The selected file is being attached to this NAV exception so the next review round can use explicit evidence.",
      targetStep: 2,
      stages: [
        ["Supporting file", "active", "Upload and link evidence to the exception"],
        ["Exception state", "queued", "Refresh the auditable exception record"],
        ["Review round", "queued", "Updated evidence will be available to the next review step"],
      ],
    },
    exception_ignore: {
      kicker: "Exception update in progress",
      title: "Recording the ignore decision",
      copy: "Cherry is preserving the Fund Manager's explicit reason and note against this exception.",
      targetStep: 2,
      stages: [
        ["Human reason", "done", "Explicit reason supplied by the reviewer"],
        ["Audit update", "active", "Record the ignore decision against the exception"],
        ["Exception queue", "queued", "Refresh the remaining NAV findings"],
      ],
    },
    processing: {
      kicker: "NAV workflow in progress",
      title: "Processing this NAV control step",
      copy: "Cherry is waiting for the server to complete the requested workflow action.",
      targetStep: null,
      stages: [
        ["Request received", "done", "The workflow request has started"],
        ["Server processing", "active", "Waiting for the completed response"],
        ["Case refresh", "queued", "The UI will update from returned case data"],
      ],
    },
  };
  const state = {
    caseData: null,
    history: null,
    busy: false,
    busyAction: null,
    busyStartedAt: null,
    busyTimer: null,
    viewStep: null,
  };

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

  function syncControlLauncher() {
    const stage = document.querySelector("#fm-stage");
    if (!stage) return;
    const executeButton = stage.querySelector("#fm-execute");
    const existingLauncher = stage.querySelector("#fm-start-nav");

    if (!executeButton || !state.caseData) {
      existingLauncher?.remove();
      return;
    }

    const actions = executeButton.closest(".fm-actions");
    if (!actions || existingLauncher) return;

    const navButton = document.createElement("button");
    navButton.type = "button";
    navButton.id = "fm-start-nav";
    navButton.className = "fm-button secondary";
    navButton.textContent = "NAV Quality Controller →";
    navButton.title = navApplicable()
      ? "Open NAV Quality Controller using the evidence already uploaded to this case."
      : "Open NAV Quality Controller and add NAV evidence if required.";
    navButton.addEventListener("click", () => window.setFundManagerTab?.("nav"));
    actions.appendChild(navButton);
  }

  function rememberCase(payload, { broadcast = true } = {}) {
    if (!payload?.case_id) return;
    state.caseData = payload;
    state.viewStep = null;
    localStorage.setItem(CASE_KEY, payload.case_id);
    render();
    queueMicrotask(syncControlLauncher);
    if (broadcast) window.dispatchEvent(new CustomEvent("fund-manager-case-updated", { detail: payload }));
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
  }

  function pill(status) {
    const value = String(status || "review");
    return `<span class="navqc-pill ${esc(value)}">${esc(value.replaceAll("_", " "))}</span>`;
  }

  function header() {
    return `<div class="navqc-head"><div><p class="eyebrow">Fund Manager · NAV controls</p><h2>NAV Quality Controller</h2>
      <p>Uses the evidence already uploaded to this case. Add only new or missing evidence when required.</p></div>
      <div class="navqc-actions"><span class="navqc-case">${state.caseData ? `Case ${esc(state.caseData.case_id)}` : "No active case"}</span>
      <button type="button" class="navqc-button secondary" id="navqc-exit" ${state.busy ? "disabled" : ""}>← Back to General Document Review</button></div></div>`;
  }

  function busyTargetStep() {
    const configured = BUSY_STATES[state.busyAction]?.targetStep;
    return configured == null ? currentStep() : configured;
  }

  function stepper() {
    const current = state.busy ? busyTargetStep() : currentStep();
    const viewing = state.busy ? current : displayedStep();
    return `<div class="navqc-stepper">${STEPS.map((label, index) => {
      const cls = index < current ? "done" : index === current ? "active" : "";
      const historical = !state.busy && index === viewing && viewing !== current ? " viewing" : "";
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
    return '<div class="navqc-panel"><h3>Upload evidence first</h3><div class="navqc-empty">NAV Quality Control starts after a Fund Manager case has been created.</div></div>';
  }

  function busyActionFor(path) {
    if (path.endsWith("/nav/readiness")) return "readiness";
    if (path.endsWith("/nav/reconcile")) return "reconcile";
    if (path.endsWith("/nav/review")) return "review";
    if (path.endsWith("/nav/decision")) return "decision";
    if (path.includes("/nav/exceptions/") && path.endsWith("/evidence")) return "exception_evidence";
    if (path.includes("/nav/exceptions/") && path.endsWith("/ignore")) return "exception_ignore";
    if (path.endsWith("/evidence")) return "evidence";
    return "processing";
  }

  function navEvidenceCount() {
    const sources = state.caseData?.classification?.sources || [];
    return sources.filter((source) => source.validation_status === "accepted" && NAV_TYPES.has(source.detected_type)).length;
  }

  function elapsedText() {
    if (!state.busyStartedAt) return "Starting…";
    const seconds = Math.max(0, Math.floor((Date.now() - state.busyStartedAt) / 1000));
    if (seconds < 60) return `${seconds}s elapsed`;
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s elapsed`;
  }

  function refreshBusyClock() {
    const node = document.querySelector("#navqc-busy-elapsed");
    if (node) node.textContent = elapsedText();
  }

  function stopBusyClock() {
    if (state.busyTimer != null) window.clearInterval(state.busyTimer);
    state.busyTimer = null;
  }

  function startBusyClock() {
    stopBusyClock();
    refreshBusyClock();
    state.busyTimer = window.setInterval(refreshBusyClock, 1000);
  }

  function busyView() {
    const config = BUSY_STATES[state.busyAction] || BUSY_STATES.processing;
    const sourceCount = navEvidenceCount();
    const stages = config.stages.map(([label, status, detail]) => `<div class="navqc-activity-row ${esc(status)}">
      <span class="navqc-activity-icon" aria-hidden="true"></span><div><strong>${esc(label)}</strong><small>${esc(detail)}</small></div>
      <span class="navqc-activity-state">${status === "done" ? "Complete" : status === "active" ? "In progress" : "Waiting"}</span></div>`).join("");
    return `<div class="navqc-panel navqc-busy-panel" role="status" aria-live="polite">
      <div class="navqc-busy-hero"><div class="navqc-spinner" aria-hidden="true"></div><div class="navqc-busy-copy">
        <p class="eyebrow">${esc(config.kicker)}</p><h3>${esc(config.title)}</h3><p>${esc(config.copy)}</p>
        <div class="navqc-busy-meta"><span>${state.caseData ? `Case ${esc(state.caseData.case_id)}` : "NAV workflow"}</span><span>${sourceCount} NAV source${sourceCount === 1 ? "" : "s"}</span><span id="navqc-busy-elapsed">${esc(elapsedText())}</span></div>
      </div></div>
      <div class="navqc-activity" aria-label="NAV processing activity">${stages}</div>
      <div class="navqc-busy-note"><strong>Live status, not a fake percentage.</strong><span>This endpoint returns a completed step rather than streaming stage progress. Cherry keeps the current server activity visible and updates the control result only when the response arrives.</span></div>
    </div>`;
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
      <div class="navqc-grid">${relevant.map((source) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(source.filename)}</strong>${pill(source.validation_status === "accepted" ? "ready" : "review")}</div><p>${esc(source.detected_type)}</p></div>`).join("") || '<div class="navqc-empty">No NAV-specific evidence identified yet. Add new or missing evidence below if NAV review is required.</div>'}</div>
      ${current ? evidenceUploadPanel() : ""}<div class="navqc-actions">${current ? '<button class="navqc-button primary" id="navqc-readiness">Check readiness →</button>' : historicalNav()}</div></div>`;
  }

  function readinessAccept(key) {
    return key === "source_ledger"
      ? ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      : ".json,application/json";
  }

  function readinessView(readiness) {
    const inputs = readiness.inputs || {};
    const rows = [
      ["nav_summary", "Administrator NAV summary", inputs.nav_summary, false],
      ["source_ledger", "Investor-level GL", inputs.source_ledger, false],
      ["side_letter_rules", "Structured side-letter rules", inputs.side_letter_rules, false],
    ];
    const current = currentStep() === 1;
    return `<div class="navqc-panel"><h3>Readiness</h3><p>Confirm the available NAV inputs before reconciliation. Missing optional evidence can be added directly to the relevant section.</p>
      <div class="navqc-grid">${rows.map(([key, label, item, required]) => `<div class="navqc-item"><div class="navqc-item-head"><strong>${esc(label)}</strong>${pill(item ? "ready" : required ? "needs_review" : "optional_evidence")}</div><p>${item ? esc(item.filename) : "Not supplied / not identified"}</p>${!item && current ? `<div class="navqc-actions"><button type="button" class="navqc-button secondary" data-readiness-upload="${esc(key)}">Upload evidence</button><input type="file" hidden data-readiness-file="${esc(key)}" accept="${esc(readinessAccept(key))}"></div>` : ""}</div>`).join("")}</div>
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
    const caseId = encodeURIComponent(state.caseData?.case_id || "");
    return `<div class="navqc-panel"><h3>NAV decision recorded</h3><p><strong>${esc(String(decision.action || "recorded").replaceAll("_", " "))}</strong></p>
      ${decision.note ? `<p>${esc(decision.note)}</p>` : ""}
      <div class="navqc-boundary"><strong>Summary report ready</strong><p>Download the final NAV review, evidence summary, findings and recorded human decision.</p>
      <div class="navqc-actions"><a class="navqc-button primary" href="/api/fund-manager/cases/${caseId}/nav/report.pdf" download>Download summary PDF ↓</a><a class="navqc-button secondary" href="/api/fund-manager/cases/${caseId}/nav/report.xlsx" download>Download Excel report ↓</a></div></div>
      <div class="navqc-actions"><button class="navqc-button secondary" id="navqc-back">← Back</button><button class="navqc-button secondary" id="navqc-history">View history</button></div></div>`;
  }

  function historyView() {
    if (!state.history) return "";
    if (!state.history.available) return `<div class="navqc-panel"><h3>Review history</h3><div class="navqc-empty">${esc(state.history.reason)}</div></div>`;
    const history = state.history.history || {};
    const rounds = history.history || history.rounds || history.iterations || [];
    return `<div class="navqc-panel"><h3>Review history</h3><div class="navqc-history">${rounds.map((round) => `<div class="navqc-round"><span>Round ${esc(round.round_number)}</span><strong>${esc(String(round.action || "review").replaceAll("_", " "))}</strong><span>${esc(round.exceptions_open ?? 0)} exceptions</span></div>`).join("")}</div></div>`;
  }

  function render() {
    const root = document.querySelector("#navqc-content");
    if (!root) return;
    root.setAttribute("aria-busy", String(state.busy));
    const nav = workflow();
    let body = state.busy ? busyView() : noCase();
    if (!state.busy && state.caseData) {
      const view = displayedStep();
      if (view === 0) body = evidence();
      else if (view === 1) body = readinessView(nav.readiness || {});
      else if (view === 2) body = reconciliationView(nav.reconciliation || {});
      else if (view === 3) body = reviewView(nav.review || {});
      else body = nav.decision ? decidedView(nav.decision) : decisionView(nav.review || {});
    }
    root.innerHTML = `${header()}${stepper()}${body}${state.busy ? "" : historyView()}`;
    bind();
  }

  async function run(path, options = { method: "POST" }) {
    if (state.busy || !state.caseData) return false;
    state.busy = true;
    state.busyAction = busyActionFor(path);
    state.busyStartedAt = Date.now();
    render();
    startBusyClock();
    let succeeded = false;
    try {
      rememberCase(await api(path, options));
      succeeded = true;
    } catch (error) {
      notify(error.message || "NAV workflow step failed.", true);
    } finally {
      stopBusyClock();
      state.busy = false;
      state.busyAction = null;
      state.busyStartedAt = null;
      render();
    }
    return succeeded;
  }

  async function uploadGenericEvidence() {
    const input = document.querySelector("#navqc-new-evidence");
    const file = input?.files?.[0];
    if (!file || !state.caseData) return;
    const form = new FormData();
    form.append("files", file);
    const succeeded = await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/evidence`, { method: "POST", body: form });
    if (succeeded) notify("Evidence added. NAV workflow state has been refreshed.");
  }

  async function uploadReadinessEvidence(key, file) {
    if (!file || state.busy || !state.caseData) return;
    const caseId = state.caseData.case_id;
    const form = new FormData();
    form.append("files", file);
    const added = await run(`/api/fund-manager/cases/${encodeURIComponent(caseId)}/evidence`, { method: "POST", body: form });
    if (!added) return;
    const refreshed = await run(`/api/fund-manager/cases/${encodeURIComponent(caseId)}/nav/readiness`);
    if (refreshed) notify(`${key.replaceAll("_", " ")} evidence added and readiness rechecked.`);
  }

  async function uploadEvidence(key, file) {
    if (!file || state.busy) return;
    const form = new FormData();
    form.append("file", file);
    const succeeded = await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/evidence`, { method: "POST", body: form });
    if (succeeded) notify("Supporting evidence added to this exception.");
  }

  async function ignoreException(key) {
    const reason = window.prompt("Reason for ignoring this exception (required):");
    if (!reason?.trim()) return;
    const note = window.prompt("Optional supporting note:") || null;
    const succeeded = await run(`/api/fund-manager/cases/${encodeURIComponent(state.caseData.case_id)}/nav/exceptions/${encodeURIComponent(key)}/ignore`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason.trim(), note }),
    });
    if (succeeded) notify("Exception ignored with an auditable reason.");
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
      queueMicrotask(syncControlLauncher);
    });
    document.querySelector("#navqc-back")?.addEventListener("click", goBack);
    document.querySelector("#navqc-current-step")?.addEventListener("click", () => {
      state.viewStep = null;
      render();
    });
    document.querySelector("#navqc-readiness")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-refresh")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/readiness`));
    document.querySelector("#navqc-reconcile")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/reconcile`));
    document.querySelector("#navqc-review")?.addEventListener("click", () => run(`/api/fund-manager/cases/${encodeURIComponent(id)}/nav/review`));
    document.querySelector("#navqc-decision-step")?.addEventListener("click", () => {
      state.viewStep = 4;
      render();
    });
    document.querySelector("#navqc-history")?.addEventListener("click", loadHistory);
    document.querySelector("#navqc-upload-new-evidence")?.addEventListener("click", uploadGenericEvidence);
    document.querySelectorAll("[data-readiness-upload]").forEach((button) => {
      button.addEventListener("click", () => document.querySelector(`[data-readiness-file="${CSS.escape(button.dataset.readinessUpload)}"]`)?.click());
    });
    document.querySelectorAll("[data-readiness-file]").forEach((input) => {
      input.addEventListener("change", () => uploadReadinessEvidence(input.dataset.readinessFile, input.files?.[0]));
    });
    document.querySelectorAll("[data-upload-exception]").forEach((button) => {
      button.addEventListener("click", () => document.querySelector(`[data-exception-file="${CSS.escape(button.dataset.uploadException)}"]`)?.click());
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
          body: JSON.stringify({ action: button.dataset.navDecision, note: document.querySelector("#navqc-note")?.value || null }),
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
    stopBusyClock();
    state.caseData = null;
    state.history = null;
    state.busy = false;
    state.busyAction = null;
    state.busyStartedAt = null;
    state.viewStep = null;
    window.setFundManagerTab?.("general");
    render();
    queueMicrotask(syncControlLauncher);
  });
  window.addEventListener("fund-manager-nav-tab-opened", () => render());

  injectStyles();
  document.addEventListener("DOMContentLoaded", async () => {
    mount();
    await restore();
    window.setFundManagerTab?.("general");
    syncControlLauncher();
  });
})();
