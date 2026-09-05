const state = { case: null, config: null, batchCases: [] };
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
  const studioStatus = payload.agent_studio?.status ? ` · Agent Studio ${titleise(payload.agent_studio.status)}` : "";
  const cashStatus = payload.cash_feed_supplied === false ? " · Cash evidence pending" : "";
  $("#case-title").textContent = `${extraction.investor_name || "Unknown investor"} · ${extraction.notice_id || "Unreferenced notice"}`;
  $("#case-subtitle").textContent = `${extraction.fund_name} · ${payload.synthetic ? "Synthetic demonstration" : "Uploaded evidence"}${payload.source_pdf ? ` · ${payload.source_pdf}` : ""}${cashStatus}${studioStatus}`;
  $("#decision-badge").textContent = actionLabel; $("#decision-badge").className = `decision-badge ${actionClass}`;
  $("#metric-expected").textContent = money(analysis.expected_amount, code); $("#metric-received").textContent = money(analysis.received_amount, code); $("#metric-progress").textContent = `${analysis.funding_progress_percent}% funded`; $("#metric-outstanding").textContent = money(analysis.outstanding_amount, code); $("#metric-variance").textContent = `${money(analysis.variance_amount, code)} net variance`; $("#outstanding-card").classList.toggle("metric-alert", Number(analysis.outstanding_amount) > 0);
  const due = analysis.days_to_due; $("#metric-due").textContent = due == null ? "—" : due < 0 ? `${Math.abs(due)}d overdue` : due === 0 ? "Due today" : `${due} day${due === 1 ? "" : "s"}`; $("#metric-due-date").textContent = dateLabel(analysis.due_date);
  $("#extraction-confidence").textContent = `${extraction.confidence}% confidence`; $("#notice-fund").textContent = extraction.fund_name; $("#notice-id").textContent = extraction.notice_id || "—"; $("#notice-investor").textContent = extraction.investor_name || "Not stated"; $("#notice-due").textContent = dateLabel(extraction.due_date); $("#notice-amount").textContent = money(extraction.current_call, code); $("#notice-reference").textContent = extraction.payment_reference || "Not stated"; $("#notice-bank").textContent = extraction.bank_name || "Bank not stated"; $("#notice-account").textContent = extraction.account_last4 ? `•••• ${extraction.account_last4}` : "Account incomplete";
  renderFindings(analysis.findings || []); renderTasks(analysis.work_items || [], analysis.action);
  const total = Number(analysis.total_commitment || extraction.total_commitment || 0); const before = Number(analysis.called_before_current || extraction.called_before_current || 0); const current = Number(extraction.current_call || 0);
  $("#total-commitment").textContent = money(total, code); $("#called-before").textContent = money(before, code); $("#current-call").textContent = money(current, code); $("#remaining-call").textContent = money(analysis.remaining_commitment, code); $("#called-bar").style.width = total ? `${Math.min(100, before / total * 100)}%` : "0%"; $("#current-bar").style.width = total ? `${Math.min(100, current / total * 100)}%` : "0%"; $("#ledger-status").textContent = `${analysis.controls_passed} passed`; $("#matched-transactions").textContent = payload.cash_feed_supplied === false ? "Cash evidence not supplied" : analysis.matched_transaction_ids?.length ? analysis.matched_transaction_ids.join(", ") : "No matching booked cash"; $("#download-review").disabled = false;
}
function renderBatchPicker(cases) {
  state.batchCases = Array.isArray(cases) ? cases : [];
  const picker = $("#batch-case-picker");
  const select = $("#batch-case-select");
  if (!picker || !select || state.batchCases.length <= 1) {
    picker?.classList.add("hidden");
    if (select) select.innerHTML = "";
    return;
  }
  select.innerHTML = state.batchCases.map((item, index) => {
    const extraction = item.extraction || {};
    const label = `${index + 1}. ${item.source_pdf || "PDF"} · ${extraction.investor_name || extraction.fund_name || "case"}`;
    return `<option value="${index}">${escapeHtml(label)}</option>`;
  }).join("");
  picker.classList.remove("hidden");
}
function updateFileCounts() {
  const pdfCount = $("#capital-call-input")?.files.length || 0;
  const excelCount = $("#commitments-input")?.files.length || 0;
  const bankStatementCount = $("#bank-statements-input")?.files.length || 0;
  if ($("#capital-call-count")) $("#capital-call-count").textContent = pdfCount ? `${pdfCount} PDF${pdfCount === 1 ? "" : "s"} selected` : "Select one or more PDFs";
  if ($("#commitments-count")) $("#commitments-count").textContent = excelCount ? `${excelCount} workbook${excelCount === 1 ? "" : "s"} selected` : "Select one or more workbooks";
  if ($("#bank-statements-count")) $("#bank-statements-count").textContent = bankStatementCount ? `${bankStatementCount} statement${bankStatementCount === 1 ? "" : "s"} selected` : "Select one or more bank statement PDFs";
}
async function runScenario(scenario, shouldScroll = true) {
  loading(true); $$('[data-scenario]').forEach((button) => button.classList.toggle("active", button.dataset.scenario === scenario));
  try { const payload = await api(`/api/private-markets/demo/${scenario}`, { method: "POST" }); renderCase(payload); renderBatchPicker([]); if (shouldScroll) $("#control-room").scrollIntoView({ behavior: "smooth", block: "start" }); toast(`${payload.analysis.controls_passed} controls passed · ${payload.analysis.exceptions_open} exceptions open.`); } catch (error) { toast(error.message, true); } finally { loading(false); }
}
async function loadConfig() {
  try { state.config = await api("/api/config"); const label = state.config.google_ready ? `${state.config.gemini_model} ready` : "Safe demo mode"; $("#cloud-state").className = `environment ${state.config.google_ready ? "ready" : "demo"}`; $("#cloud-state").innerHTML = `<i></i><span>${escapeHtml(label)}</span>`; } catch { $("#cloud-state").innerHTML = "<i></i><span>Environment unavailable</span>"; }
}
function downloadReview() {
  if (!state.case) return; const blob = new Blob([JSON.stringify(state.case, null, 2)], { type: "application/json" }); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${state.case.case_id || "private-markets-case"}-review.json`; link.click(); URL.revokeObjectURL(link.href); toast("Review brief downloaded with findings and assigned work.");
}
async function uploadEvidence(event) {
  event.preventDefault();
  const pdfFiles = [...$("#capital-call-input").files];
  const excelFiles = [...$("#commitments-input").files];
  const jsonFile = $("#cash-input").files[0] || null;
  const bankStatementFiles = [...$("#bank-statements-input").files];
  if (!pdfFiles.length || !excelFiles.length) {
    toast("Select at least one PDF and one Excel workbook.", true);
    return;
  }
  const form = new FormData();
  pdfFiles.forEach((file) => form.append("capital_call", file));
  excelFiles.forEach((file) => form.append("commitments", file));
  if (jsonFile) form.append("fund_json", jsonFile);
  bankStatementFiles.forEach((file) => form.append("bank_statements", file));
  if ($("#as-of-input").value) form.append("as_of_date", $("#as-of-input").value);
  const token = $("#upload-token")?.value.trim();
  const headers = token ? { "X-Cherry-Demo-Token": token } : {};
  const cashLabel = [jsonFile ? "one JSON cash feed" : null, bankStatementFiles.length ? `${bankStatementFiles.length} bank statement${bankStatementFiles.length === 1 ? "" : "s"}` : null].filter(Boolean).join(" + ") || "no cash evidence";
  $("#upload-message").textContent = `Processing ${pdfFiles.length} PDF${pdfFiles.length === 1 ? "" : "s"} and ${excelFiles.length} Excel workbook${excelFiles.length === 1 ? "" : "s"} with ${cashLabel}…`;
  loading(true);
  try {
    const result = await api("/api/private-markets/analyse-integrated", { method: "POST", body: form, headers });
    const cases = Array.isArray(result.cases) && result.cases.length ? result.cases : [result];
    renderBatchPicker(cases);
    renderCase({ ...cases[0], synthetic: false, transactions: [] });
    const batch = result.batch || { pdf_count: pdfFiles.length, excel_count: excelFiles.length, case_count: cases.length, json_count: jsonFile ? 1 : 0, bank_statement_count: bankStatementFiles.length };
    const cashSummary = (batch.json_count || batch.bank_statement_count) ? "cash evidence included" : "cash evidence pending";
    $("#upload-message").textContent = `Batch ${result.batch_id || result.case_id}: ${batch.case_count} governed case${batch.case_count === 1 ? "" : "s"} from ${batch.pdf_count} PDF${batch.pdf_count === 1 ? "" : "s"} + ${batch.excel_count} Excel workbook${batch.excel_count === 1 ? "" : "s"}; ${cashSummary}.`;
    $("#control-room").scrollIntoView({ behavior: "smooth" });
    toast(`${batch.case_count} case${batch.case_count === 1 ? "" : "s"} analysed · ${cashSummary}.`);
  } catch (error) {
    $("#upload-message").textContent = error.message;
    renderBatchPicker([]);
    toast(error.message, true);
  } finally {
    loading(false);
  }
}
function bindEvents() {
  $$('[data-scenario]').forEach((button) => button.addEventListener("click", () => runScenario(button.dataset.scenario)));
  $("#download-review").addEventListener("click", downloadReview);
  $("#upload-form").addEventListener("submit", uploadEvidence);
  $("#capital-call-input").addEventListener("change", updateFileCounts);
  $("#commitments-input").addEventListener("change", updateFileCounts);
  $("#bank-statements-input").addEventListener("change", updateFileCounts);
  $("#batch-case-select").addEventListener("change", (event) => {
    const selected = state.batchCases[Number(event.target.value)];
    if (selected) renderCase({ ...selected, synthetic: false, transactions: [] });
  });
}
async function initialise() { bindEvents(); updateFileCounts(); await loadConfig(); await runScenario("exception", false); }
document.addEventListener("DOMContentLoaded", initialise);
