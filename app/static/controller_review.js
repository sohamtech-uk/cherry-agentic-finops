const CASE_ID = "CA-05-RCPT-1042-500";
const state = { packet: null, reviewers: [], action: "leave_balance_open" };
const $ = (selector) => document.querySelector(selector);

function money(value, currency = "GBP") {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(Number(value));
}

function label(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body = {};
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) throw new Error(body.detail?.message || body.detail || `${response.status} ${response.statusText}`);
  return body;
}

function showMessage(message, success = false) {
  const node = $("#message");
  node.textContent = message;
  node.classList.remove("hidden");
  node.classList.toggle("success", success);
}

function renderActions(actions) {
  $("#action-grid").innerHTML = actions.map((item) => `
    <button class="action ${item.action === state.action ? "active" : ""}" type="button" data-action="${escapeHtml(item.action)}">
      <b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.accounting_effect)}</small>
    </button>`).join("");
  document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
    state.action = button.dataset.action;
    renderActions(state.packet.allowed_actions);
    updateConditionalFields();
  }));
}

function updateConditionalFields() {
  const reasonActions = ["approve_write_off", "create_dispute"];
  $("#reason-field").classList.toggle("hidden", !reasonActions.includes(state.action));
  $("#owner-field").classList.toggle("hidden", state.action !== "create_dispute");
  $("#evidence-field").classList.toggle("hidden", state.action !== "request_evidence");
}

function renderPacket(packet) {
  state.packet = packet;
  const receipt = packet.receipt;
  const match = packet.customer_invoice_match;
  const ar = packet.remaining_ar_state;
  $("#case-summary").textContent = `${receipt.receipt_id}: ${money(receipt.amount, receipt.currency)} received against ${match.invoice_id}; the ${money(packet.amount_at_risk, receipt.currency)} short-pay needs an accounting decision.`;
  $("#amount-risk").textContent = money(packet.amount_at_risk, receipt.currency);
  $("#review-status").textContent = label(packet.review_status);
  $("#receipt-id").textContent = receipt.receipt_id;
  $("#transaction-id").textContent = `${receipt.source_system} / ${receipt.source_transaction_id}`;
  $("#payer").textContent = receipt.payer_name;
  $("#booking-date").textContent = new Date(`${receipt.booking_date}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  $("#receipt-amount").textContent = `${money(receipt.amount, receipt.currency)} · ${receipt.settlement_status} / ${receipt.allocation_status}`;
  $("#customer").textContent = `${match.customer_name} · ${match.customer_id}`;
  $("#invoice-id").textContent = match.invoice_id;
  $("#invoice-before").textContent = money(match.invoice_open_balance_before, match.invoice_currency);
  $("#cash-allocation").textContent = money(match.proposed_cash_application, match.invoice_currency);
  $("#reason-code").textContent = `${match.remittance_raw_reason} · located customer claim, not independently proven`;
  $("#match-basis").innerHTML = match.match_basis.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  $("#bridge-before").textContent = money(ar.invoice_balance_before, match.invoice_currency);
  $("#bridge-cash").textContent = money(ar.cash_applied, match.invoice_currency);
  $("#bridge-treatment").textContent = money(ar.authorised_adjustment, match.invoice_currency);
  $("#bridge-open").textContent = money(ar.open_balance, match.invoice_currency);
  const proposed = packet.proposed_after_valid_decision;
  $("#state-label").textContent = packet.application_status === "REVIEW_REQUIRED"
    ? `${ar.invoice_id} remains ${money(ar.open_balance, match.invoice_currency)} open and ${receipt.receipt_id} is HELD: no ledger mutation before review. A valid leave-open/dispute decision would post ${money(proposed.cash_applied, receipt.currency)} and preserve ${money(proposed.open_balance, match.invoice_currency)} open.`
    : `${ar.invoice_id} is ${ar.invoice_state}; receipt allocation is ${ar.receipt_allocation_status} with ${money(ar.receipt_unapplied_amount, receipt.currency)} unapplied.`;
  $("#stop-reasons").innerHTML = packet.automation_stopped.map((item) => `<div class="stop-reason"><b>${escapeHtml(item.code)}</b><p>${escapeHtml(item.explanation)}</p></div>`).join("");
  $("#policy-heading").textContent = `${packet.policy.policy_id} · v${packet.policy.version}`;
  $("#policy-meta").textContent = `Effective ${packet.policy.effective_from} · automatic limit ${money(packet.policy.max_auto_writeoff_gbp)}`;
  $("#policy-clauses").innerHTML = packet.policy.clauses.map((item) => `<div class="policy-clause"><b>Clause ${escapeHtml(item.clause)}</b><p>${escapeHtml(item.requirement)}</p></div>`).join("");
  $("#control-list").innerHTML = packet.control_checks.map((item) => `<div class="control ${item.outcome === "PASS" ? "" : "failed"}"><b>${escapeHtml(item.outcome)} · ${escapeHtml(item.code)}</b><small>${escapeHtml(item.explanation)}</small></div>`).join("");
  $("#evidence-list").innerHTML = packet.evidence.map((item) => `<div class="evidence-item"><div class="evidence-type">${escapeHtml(label(item.source_type))}</div><div><code>${escapeHtml(item.source_system)} / ${escapeHtml(item.source_object_id)} · ${escapeHtml(item.locator)}</code><p>${escapeHtml(item.supports)}</p><code class="hash">SHA-256 · ${escapeHtml(item.source_sha256)}</code></div></div>`).join("");
  $("#audit-list").innerHTML = packet.audit_events.map((event) => `<div class="audit-item"><span>${event.sequence}</span><div><b>${escapeHtml(label(event.action))}</b><p>${escapeHtml(JSON.stringify(event.details))}</p><code>${escapeHtml(event.event_hash)}</code></div></div>`).join("");
  renderActions(packet.allowed_actions);
  updateConditionalFields();

  const decided = Boolean(packet.recorded_decision);
  $("#submit-decision").disabled = decided;
  if (decided) {
    const decision = packet.recorded_decision;
    $("#decision-result").innerHTML = `<h3>${escapeHtml(label(decision.action))}</h3><p>Recorded by ${escapeHtml(decision.reviewer_name)} · ${escapeHtml(decision.rationale)} · simulated only.</p>`;
    $("#decision-result").classList.remove("hidden");
  } else {
    $("#decision-result").classList.add("hidden");
  }
}

function renderAgentInvestigation(result) {
  state.action = result.recommended_action;
  renderActions(state.packet.allowed_actions);
  updateConditionalFields();
  $("#agent-action").textContent = label(result.recommended_action);
  $("#agent-summary").textContent = result.recommendation_label;
  $("#agent-model").textContent = `${result.provider} · ${result.model} · ${result.model_response_ids.join(" / ")}`;
  $("#agent-claims").innerHTML = result.grounded_claims.map((claim) => `
    <div class="grounded-claim">
      <b>${escapeHtml(claim.claim_id)}</b>
      <p>${escapeHtml(claim.statement)}</p>
      <small>Evidence · ${claim.evidence_ids.map(escapeHtml).join(" · ")}</small>
    </div>`).join("");
  $("#agent-trajectory").innerHTML = result.trajectory.map((step) => `
    <div class="trajectory-step">
      <span>${step.sequence}</span>
      <div><b>${escapeHtml(step.kind)} · ${escapeHtml(step.name)}</b><code>${escapeHtml(JSON.stringify(step.detail))}</code></div>
    </div>`).join("");
  $("#agent-placeholder").classList.add("hidden");
  $("#agent-result").classList.remove("hidden");
}

async function runAgentInvestigation() {
  const button = $("#run-agent");
  button.disabled = true;
  button.textContent = "Investigating packet…";
  $("#agent-placeholder").classList.remove("agent-error");
  $("#agent-placeholder").textContent = "Calling the model with one read-only investigation tool…";
  try {
    const result = await api(`/api/controller-review/cases/${CASE_ID}/agent-investigation`, { method: "POST" });
    renderAgentInvestigation(result);
    showMessage("Grounded agent advice is ready. No decision was recorded and no ledger state changed.", true);
  } catch (error) {
    $("#agent-result").classList.add("hidden");
    $("#agent-placeholder").classList.remove("hidden");
    $("#agent-placeholder").classList.add("agent-error");
    $("#agent-placeholder").textContent = `${error.message} Deterministic review remains available; no accounting state changed.`;
  } finally {
    button.disabled = false;
    button.textContent = "Run investigation agent";
  }
}

async function runCleanScenario() {
  const button = $("#run-clean");
  button.disabled = true;
  button.textContent = "Running controls…";
  try {
    const response = await api("/api/controller-review/demo/clean-multi-invoice", { method: "POST" });
    const outcome = response.outcome;
    const allocations = outcome.applications.map((item) => `${item.invoice_id} ${money(item.amount)}`).join(" + ");
    $("#clean-result").classList.add("complete");
    $("#clean-result").innerHTML = `<span class="status-dot"></span><div><small>${escapeHtml(outcome.application.status)} · ${escapeHtml(outcome.application.application_kind)}</small><strong>${escapeHtml(allocations)}</strong><p>Receipt residual ${escapeHtml(money(outcome.receipt.unapplied_amount))} · ${outcome.audit_events.length} hash-linked audit events · SIMULATED only</p></div>`;
    button.textContent = "Run again from fresh simulated state";
  } catch (error) {
    showMessage(error.message);
    button.textContent = "Retry deterministic application";
  } finally {
    button.disabled = false;
  }
}

async function loadReviewers() {
  state.reviewers = await api("/api/controller-review/reviewers");
  $("#reviewer").innerHTML = state.reviewers.map((reviewer) => `<option value="${escapeHtml(reviewer.reviewer_id)}">${escapeHtml(reviewer.reviewer_name)} · ${escapeHtml(reviewer.role)} · ${money(reviewer.approval_limit_gbp)} approval limit</option>`).join("");
  $("#reviewer").value = "controller_uk_01";
}

async function loadPacket() {
  renderPacket(await api(`/api/controller-review/cases/${CASE_ID}`));
}

async function resetDemo() {
  try {
    renderPacket(await api("/api/controller-review/demo/short-pay-500/reset", { method: "POST" }));
    $("#rationale").value = "";
    $("#agent-result").classList.add("hidden");
    $("#agent-placeholder").classList.remove("hidden", "agent-error");
    $("#agent-placeholder").textContent = "Ready · model access is isolated from the decision endpoint.";
    showMessage("The £500 short-pay case was reset to awaiting controller review.", true);
  } catch (error) { showMessage(error.message); }
}

async function submitDecision(event) {
  event.preventDefault();
  const payload = {
    decision_id: `ui-${crypto.randomUUID()}`,
    reviewer_id: $("#reviewer").value,
    action: state.action,
    rationale: $("#rationale").value,
  };
  payload.expected_review_version = state.packet.review_version;
  if (["approve_write_off", "create_dispute"].includes(state.action)) payload.reason_code = $("#decision-reason").value;
  if (state.action === "create_dispute") payload.dispute_owner = $("#dispute-owner").value;
  if (state.action === "request_evidence") payload.requested_evidence = $("#requested-evidence").value;
  try {
    const packet = await api(`/api/controller-review/cases/${CASE_ID}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderPacket(packet);
    showMessage(`${label(state.action)} recorded in simulated AR. No production write occurred.`, true);
  } catch (error) { showMessage(error.message); await loadPacket(); }
}

async function initialise() {
  $("#reset-demo").addEventListener("click", resetDemo);
  $("#run-clean").addEventListener("click", runCleanScenario);
  $("#run-agent").addEventListener("click", runAgentInvestigation);
  $("#decision-form").addEventListener("submit", submitDecision);
  try {
    await Promise.all([loadReviewers(), loadPacket()]);
  } catch (error) { showMessage(error.message); }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialise, { once: true });
} else {
  initialise();
}
