const state = { case: null, config: null };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function money(value, code = "GBP") { return new Intl.NumberFormat("en-GB", { style: "currency", currency: code, maximumFractionDigits: 2 }).format(Number(value || 0)); }
function dateLabel(value) {
  if (!value) return "Not stated";
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(parsed);
}
function titleise(value) { return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function loading(visible) { $("#loading").classList.toggle("hidden", !visible); }
let toastTimer;
function toast(message, error = false) {
  const element = $("#toast"); element.textContent = message; element.classList.toggle("error", error); element.classList.add("visible"); clearTimeout(toastTimer); toastTimer = setTimeout(() => element.classList.remove("visible"), 3500);
}
async function api(path, options = {}) {
  const response = await fetch(path, options); let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}
function actionCopy(action) { return { auto_reconcile: ["Ready to reconcile", "good"], require_approval: ["Independent approval", "warning"], request_evidence: ["Hold · evidence required", "danger"] }[action] || [titleise(action), "warning"]; }

function renderFindings(findings) {
  $("#finding-count").textContent = `${findings.length} controls`;
  $("#finding-list").innerHTML = findings.map((finding) => `<div class="finding ${escapeHtml(finding.severity)}"><span class="finding-icon">${finding.severity === "pass" ? "✓" : finding.severity === "high" ? "!" : "·"}</span><div><strong>${escapeHtml(finding.title)}</strong><p>${escapeHtml(finding.detail)}</p>${finding.expected || finding.observed ? `<small>${finding.expected ? `Expected ${escapeHtml(finding.expected)}` : ""}${finding.expected && finding.observed ? " · " : ""}${finding.observed ? `Observed ${escapeHtml(finding.observed)}` : ""}</small>` : ""}</div></div>`).join("");
}
function renderTasks(tasks, action) {
  $("#task-count").textContent = `${tasks.length} open`;
  if (!tasks.length) { $("#task-list").innerHTML = `<div class="all-clear"><span>✓</span><div><strong>No intervention required</strong><p>All evidence passed deterministic controls. This case can be reconciled.</p></div></div>`; return; }
  $("#task-list").innerHTML = tasks.map((task, index) => `<div class="task"><div class="task-top"><span>${String(index + 1).padStart(2, "0")}</span><b class="priority ${escapeHtml(task.priority)}">${escapeHtml(task.priority)}</b></div><h4>${escapeHtml(task.title)}</h4><p>${escapeHtml(task.instruction)}</p><div class="task-owner"><small>OWNER</small><strong>${escapeHtml(task.owner)}</strong></div></div>`).join("");
  const [label] = actionCopy(action); $("#task-list").insertAdjacentHTML("beforeend", `<div class="queue-note"><i></i><span>Automation remains paused while the case is <b>${escapeHtml(label.toLowerCase())}</b>.</span></div>`);
}
function renderCase(payload) {
  state.case = payload; const extraction = payload.extraction; const analysis = payload.analysis; const code = extraction.currency; const [actionLabel, actionClass] = actionCopy(analysis.action);
  $("#case-title").textContent = `${extraction.investor_name || "Unknown investor"} · ${extraction.notice_id || "Unreferenced notice"}`;
  $("#case-subtitle").textContent = `${extraction.fund_name} · ${payload.synthetic ? "Synthetic demonstration" : "Uploaded evidence"}`;
  $("#decision-badge").textContent = actionLabel; $("#decision-badge").className = `decision-badge ${actionClass}`;
  $("#metric-expected").textContent = money(analysis.expected_amount, code); $("#metric-received").textContent = money(analysis.received_amount, code); $("#metric-progress").textContent = `${analysis.funding_progress_percent}% funded`; $("#metric-outstanding").textContent = money(analysis.outstanding_amount, code); $("#metric-variance").textContent = `${money(analysis.variance_amount, code)} net variance`; $("#outstanding-card").classList.toggle("metric-alert", Number(analysis.outstanding_amount) > 0);
  const due = analysis.days_to_due; $("#metric-due").textContent = due == null ? "—" : due < 0 ? `${Math.abs(due)}d overdue` : due === 0 ? "Due today" : `${due} day${due === 1 ? "" : "s"}`; $("#metric-due-date").textContent = dateLabel(analysis.due_date);
  $("#extraction-confidence").textContent = `${extraction.confidence}% confidence`; $("#notice-fund").textContent = extraction.fund_name; $("#notice-id").textContent = extraction.notice_id || "—"; $("#notice-investor").textContent = extraction.investor_name || "Not stated"; $("#notice-due").textContent = dateLabel(extraction.due_date); $("#notice-amount").textContent = money(extraction.current_call, code); $("#notice-reference").textContent = extraction.payment_reference || "Not stated"; $("#notice-bank").textContent = extraction.bank_name || "Bank not stated"; $("#notice-account").textContent = extraction.account_last4 ? `•••• ${extraction.account_last4}` : "Account incomplete";
  renderFindings(analysis.findings || []); renderTasks(analysis.work_items || [], analysis.action);
  const total = Number(analysis.total_commitment || extraction.total_commitment || 0); const before = Number(analysis.called_before_current || extraction.called_before_current || 0); const current = Number(extraction.current_call || 0);
  $("#total-commitment").textContent = money(total, code); $("#called-before").textContent = money(before, code); $("#current-call").textContent = money(current, code); $("#remaining-call").textContent = money(analysis.remaining_commitment, code); $("#called-bar").style.width = total ? `${Math.min(100, before / total * 100)}%` : "0%"; $("#current-bar").style.width = total ? `${Math.min(100, current / total * 100)}%` : "0%"; $("#ledger-status").textContent = `${analysis.controls_passed} passed`; $("#matched-transactions").textContent = analysis.matched_transaction_ids?.length ? analysis.matched_transaction_ids.join(", ") : "No matching booked cash"; $("#download-review").disabled = false;
}
async function runScenario(scenario, shouldScroll = true) {
  loading(true); $$('[data-scenario]').forEach((button) => button.classList.toggle("active", button.dataset.scenario === scenario));
  try { const payload = await api(`/api/private-markets/demo/${scenario}`, { method: "POST" }); renderCase(payload); if (shouldScroll) $("#control-room").scrollIntoView({ behavior: "smooth", block: "start" }); toast(`${payload.analysis.controls_passed} controls passed · ${payload.analysis.exceptions_open} exceptions open.`); } catch (error) { toast(error.message, true); } finally { loading(false); }
}
async function loadConfig() {
  try { state.config = await api("/api/config"); const label = state.config.google_ready ? `${state.config.gemini_model} ready` : "Safe demo mode"; $("#cloud-state").className = `environment ${state.config.google_ready ? "ready" : "demo"}`; $("#cloud-state").innerHTML = `<i></i><span>${escapeHtml(label)}</span>`; } catch { $("#cloud-state").innerHTML = "<i></i><span>Environment unavailable</span>"; }
}
function downloadReview() {
  if (!state.case) return; const blob = new Blob([JSON.stringify(state.case, null, 2)], { type: "application/json" }); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${state.case.case_id || "private-markets-case"}-review.json`; link.click(); URL.revokeObjectURL(link.href); toast("Review brief downloaded with findings and assigned work.");
}
async function uploadEvidence(event) {
  event.preventDefault();
  const form = new FormData();
  form.append("capital_call", $("#capital-call-input").files[0]);
  form.append("commitments", $("#commitments-input").files[0]);
  form.append("cash", $("#cash-input").files[0]);
  if ($("#as-of-input").value) form.append("as_of_date", $("#as-of-input").value);
  const token = $("#upload-token")?.value.trim();
  const headers = token ? { "X-Cherry-Demo-Token": token } : {};
  $("#upload-message").textContent = "Extracting notice and running strict deterministic controls…";
  loading(true);
  try {
    const result = await api("/api/private-markets/analyse", { method: "POST", body: form, headers });
    renderCase({ ...result, synthetic: false, transactions: [] });
    $("#upload-message").textContent = `Case ${result.case_id} created with evidence hashes.`;
    $("#control-room").scrollIntoView({ behavior: "smooth" });
    toast("Uploaded evidence analysed with strict controls.");
  } catch (error) {
    $("#upload-message").textContent = error.message;
    toast(error.message, true);
  } finally {
    loading(false);
  }
}
function bindEvents() { $$('[data-scenario]').forEach((button) => button.addEventListener("click", () => runScenario(button.dataset.scenario))); $("#download-review").addEventListener("click", downloadReview); $("#upload-form").addEventListener("submit", uploadEvidence); }
async function initialise() { bindEvents(); await loadConfig(); await runScenario("exception", false); }
document.addEventListener("DOMContentLoaded", initialise);
