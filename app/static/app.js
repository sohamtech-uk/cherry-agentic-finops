const state = {
  workflow: null,
  config: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function currency(amount, code = "GBP") {
  const numeric = Number(amount ?? 0);
  try {
    return new Intl.NumberFormat("en-GB", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 2,
    }).format(numeric);
  } catch {
    return `${code} ${numeric.toFixed(2)}`;
  }
}

function formatDate(value) {
  if (!value) return "Not stated";
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(parsed);
}

function formatTime(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? ""
    : new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(parsed);
}

function titleise(value) {
  return String(value ?? "")
    .replaceAll("_", " ")
    .replaceAll(".", " · ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function showLoading(visible) {
  $("#loading-overlay").classList.toggle("hidden", !visible);
}

let toastTimer;
function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("visible"), 3500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return response.json();
}

async function loadConfig() {
  try {
    state.config = await api("/api/config");
    const cloudState = $("#cloud-state");
    if (state.config.google_ready) {
      cloudState.classList.add("ready");
      cloudState.innerHTML = `<span class="status-dot"></span><span>${escapeHtml(state.config.gemini_model)} · Google Cloud ready</span>`;
    } else {
      cloudState.classList.add("demo");
      cloudState.innerHTML = `<span class="status-dot"></span><span>Safe synthetic demo mode</span>`;
    }
  } catch (error) {
    $("#cloud-state").innerHTML = `<span class="status-dot"></span><span>Environment unavailable</span>`;
  }
}

function activateScenario(scenario) {
  $$(".scenario-chip").forEach((button) => {
    button.classList.toggle("active", button.dataset.scenario === scenario);
  });
}

async function runScenario(scenario) {
  showLoading(true);
  activateScenario(scenario);
  try {
    state.workflow = await api(`/api/demo/${scenario}`, { method: "POST" });
    renderWorkflow(state.workflow);
    $("#workspace").scrollIntoView({ behavior: "smooth", block: "start" });
    toast(`Workflow ${state.workflow.workflow_id} completed to ${titleise(state.workflow.status)}.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoading(false);
  }
}

function renderWorkflow(workflow) {
  $("#empty-state").classList.add("hidden");
  $("#workspace-panel").classList.remove("hidden");

  const extraction = workflow.extraction;
  const topCandidate = workflow.candidates?.[0];
  const decision = workflow.decision;

  $("#metric-workflow").textContent = workflow.workflow_id;
  $("#metric-source").textContent = workflow.source_name;
  $("#metric-confidence").textContent = `${extraction.confidence}%`;
  $("#metric-match").textContent = topCandidate ? `${topCandidate.score}%` : "No match";
  $("#metric-status").textContent = titleise(workflow.status);
  $("#metric-control").textContent = decision?.control || "Awaiting policy";

  $("#extraction-source").textContent = extraction.source === "gemini" ? "Gemini extracted" : "Synthetic demo";
  $("#doc-supplier").textContent = extraction.supplier_name;
  $("#doc-number").textContent = extraction.invoice_number || "Not stated";
  $("#doc-date").textContent = formatDate(extraction.issue_date);
  $("#doc-due").textContent = formatDate(extraction.due_date);
  $("#doc-category").textContent = extraction.lines?.[0]?.description || extraction.suggested_category;
  $("#doc-subtotal").textContent = currency(extraction.subtotal, extraction.currency);
  $("#doc-tax").textContent = currency(extraction.tax, extraction.currency);
  $("#doc-total").textContent = currency(extraction.total, extraction.currency);
  $("#extract-category").textContent = extraction.suggested_category;
  $("#extract-vat").textContent = extraction.vat_treatment;
  $("#extract-reference").textContent = extraction.payment_reference || extraction.invoice_number || "Not stated";

  renderCandidates(workflow.candidates || []);
  renderDecision(workflow);
  renderAudit(workflow.audit_events || [], workflow.audit_chain_valid);
}

function renderCandidates(candidates) {
  $("#candidate-count").textContent = `${candidates.length} candidate${candidates.length === 1 ? "" : "s"}`;
  const container = $("#candidate-list");
  if (!candidates.length) {
    container.innerHTML = `<div class="candidate"><div class="candidate-main"><strong>No bank candidates</strong><small>Supply a candidate transaction feed to continue.</small></div></div>`;
    return;
  }
  container.innerHTML = candidates.map((candidate, index) => {
    const transaction = candidate.transaction;
    const factors = candidate.factors
      .filter((factor) => factor.maximum > 0)
      .map((factor) => `<span class="factor" title="${escapeHtml(factor.explanation)}">${escapeHtml(factor.name)} ${factor.score}/${factor.maximum}</span>`)
      .join("");
    return `
      <div class="candidate">
        <div class="candidate-score">${candidate.score}</div>
        <div class="candidate-main">
          <strong>${index === 0 ? "Best match · " : ""}${escapeHtml(transaction.merchant_name || transaction.description)}</strong>
          <small>${escapeHtml(transaction.description)} · ${formatDate(transaction.booking_date)} · ${escapeHtml(transaction.reference || "No reference")}</small>
        </div>
        <div class="candidate-amount">
          <strong>${currency(transaction.amount, transaction.currency)}</strong>
          <small>${candidate.amount_variance_percent}% variance</small>
        </div>
        <div class="factor-row">${factors}</div>
      </div>`;
  }).join("");
}

function renderDecision(workflow) {
  const decision = workflow.decision;
  const pill = $("#decision-pill");
  const ring = $("#score-ring");
  const approvalForm = $("#approval-form");
  const evidenceAction = $("#evidence-action");
  const download = $("#download-evidence");

  approvalForm.classList.add("hidden");
  evidenceAction.classList.add("hidden");
  download.classList.add("hidden");
  pill.className = "pill";

  if (!decision) return;

  $("#risk-score").textContent = decision.risk_score;
  ring.style.setProperty("--risk", `${decision.risk_score}%`);
  $("#decision-control").textContent = decision.control;
  $("#reason-list").innerHTML = decision.reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");

  if (workflow.status === "reconciled") {
    $("#decision-title").textContent = workflow.approved_by ? "Approved and reconciled" : "Safe to auto-reconcile";
    pill.textContent = workflow.approved_by ? "Human approved" : "Auto-reconciled";
    pill.classList.add("pill-good");
    download.href = `/api/workflows/${workflow.workflow_id}/evidence`;
    download.classList.remove("hidden");
  } else if (workflow.status === "awaiting_approval") {
    $("#decision-title").textContent = "Human approval required";
    pill.textContent = "Paused safely";
    pill.classList.add("pill-warning");
    approvalForm.classList.remove("hidden");
  } else if (workflow.status === "evidence_required") {
    $("#decision-title").textContent = "Exception: evidence required";
    pill.textContent = "Automation stopped";
    pill.classList.add("pill-danger");
    evidenceAction.classList.remove("hidden");
  } else if (workflow.status === "rejected") {
    $("#decision-title").textContent = "Workflow rejected";
    pill.textContent = "Closed by reviewer";
    pill.classList.add("pill-danger");
    download.href = `/api/workflows/${workflow.workflow_id}/evidence`;
    download.classList.remove("hidden");
  }
}

function renderAudit(events, valid) {
  $("#chain-status").textContent = valid ? "Hash chain valid" : "Chain verification failed";
  $("#chain-status").className = `pill ${valid ? "pill-good" : "pill-danger"}`;
  $("#audit-timeline").innerHTML = events.map((event) => {
    const summary = Object.entries(event.details || {})
      .slice(0, 2)
      .map(([key, value]) => `${titleise(key)}: ${typeof value === "object" ? JSON.stringify(value) : value}`)
      .join(" · ");
    return `
      <div class="timeline-event">
        <div class="timeline-dot">${event.sequence}</div>
        <div class="timeline-copy">
          <strong>${escapeHtml(titleise(event.action))}</strong>
          <small>${escapeHtml(event.actor)}${summary ? ` · ${escapeHtml(summary)}` : ""}</small>
        </div>
        <span class="timeline-time">${formatTime(event.occurred_at)}</span>
      </div>`;
  }).join("");
}

async function approveCurrent() {
  if (!state.workflow) return;
  const actor = $("#approver-name").value.trim();
  const note = $("#approval-note").value.trim();
  if (!actor || !note) {
    toast("Add the human approver and approval note.", true);
    return;
  }
  showLoading(true);
  try {
    state.workflow = await api(`/api/workflows/${state.workflow.workflow_id}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor, note }),
    });
    renderWorkflow(state.workflow);
    toast("Human approval recorded. The workflow resumed and reconciled.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoading(false);
  }
}

async function rejectCurrent(defaultReason = "Rejected after human review.") {
  if (!state.workflow) return;
  const actor = $("#approver-name").value.trim() || "Human reviewer";
  const reason = window.prompt("Reason for rejection", defaultReason);
  if (!reason) return;
  showLoading(true);
  try {
    state.workflow = await api(`/api/workflows/${state.workflow.workflow_id}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor, note: reason }),
    });
    renderWorkflow(state.workflow);
    toast("Workflow closed as rejected.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoading(false);
  }
}

async function uploadDocument(event) {
  event.preventDefault();
  const input = $("#document-input");
  const message = $("#upload-message");
  if (!input.files?.length) return;
  const formData = new FormData();
  formData.append("document", input.files[0]);
  formData.append("transactions_json", $("#transactions-input").value);
  message.textContent = "Processing with Gemini and deterministic controls…";
  showLoading(true);
  try {
    const response = await fetch("/api/workflows", { method: "POST", body: formData });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Document processing failed.");
    state.workflow = body;
    renderWorkflow(body);
    message.textContent = `Created ${body.workflow_id}.`;
    $("#workspace").scrollIntoView({ behavior: "smooth" });
    toast("Real document workflow created.");
  } catch (error) {
    message.textContent = error.message;
    toast(error.message, true);
  } finally {
    showLoading(false);
  }
}

function bindEvents() {
  $$('[data-scenario]').forEach((button) => {
    button.addEventListener("click", () => runScenario(button.dataset.scenario));
  });
  $("#approve-button").addEventListener("click", approveCurrent);
  $("#reject-button").addEventListener("click", () => rejectCurrent("Rejected after reviewing the high-value transaction."));
  $("#reject-exception-button").addEventListener("click", () => rejectCurrent("Closed because supporting evidence did not resolve the amount mismatch."));
  $("#upload-form").addEventListener("submit", uploadDocument);
  $("#document-input").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    const label = $(".dropzone strong");
    if (file) label.textContent = file.name;
  });
}

async function initialise() {
  bindEvents();
  await loadConfig();
}

document.addEventListener("DOMContentLoaded", initialise);
