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
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message || `${response.status} ${response.statusText}`);
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
  $("#dashboard")?.classList.remove("hidden");
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
  if ($("#capital-call-count")) $("#capital-call-count").textContent = pdfCount ? `${pdfCount} PDF${pdfCount === 1 ? "" : "s"} selected` : "Select one or more PDFs";
  if ($("#commitments-count")) $("#commitments-count").textContent = excelCount ? `${excelCount} workbook${excelCount === 1 ? "" : "s"} selected` : "LP commitments, bank working files, investor GLs and loader samples are supported";
}

function workflowStatus(status) {
  return { ready: "Ready", source_profiled: "Source profiled", ready_for_mapping: "Ready for mapping", needs_loader_sample: "Needs loader sample", review_required: "Review required" }[status] || titleise(status);
}
function renderDatasetResults(result) {
  const container = $("#dataset-results");
  const profiles = result.workbook_profiles || [];
  const workflows = result.workflows || [];
  const profileHtml = profiles.map((profile) => `<span class="dataset-chip"><b>${escapeHtml(titleise(profile.kind))}</b>${escapeHtml(profile.file_name)}</span>`).join("");
  const workflowHtml = workflows.map((workflow) => {
    if (workflow.workflow === "bank_statements_to_journal_entries") {
      const exceptions = (workflow.sample_exceptions || []).map((item) => `<div class="dataset-exception"><b>Row ${escapeHtml(item.row)}</b><span>${escapeHtml((item.reasons || []).join(" · "))}</span><p>${escapeHtml(item.narrative || "")}</p></div>`).join("");
      return `<article class="dataset-workflow"><div class="dataset-head"><div><small>SPONSOR WORKFLOW 01</small><h3>${escapeHtml(workflow.title)}</h3><p>${escapeHtml(workflow.message)}</p></div><b class="dataset-status review">${escapeHtml(workflowStatus(workflow.status))}</b></div><div class="dataset-metrics"><div><span>Statement rows</span><strong>${escapeHtml(workflow.total_transactions)}</strong></div><div><span>Journal lines</span><strong>${escapeHtml(workflow.journal_lines)}</strong><small>${workflow.journal_line_count_matches ? "2 lines per statement row ✓" : `Expected ${escapeHtml(workflow.journal_expected_lines)}`}</small></div><div><span>Counterparty gaps</span><strong>${escapeHtml(workflow.unmatched_counterparties)}</strong></div><div><span>Project gaps</span><strong>${escapeHtml(workflow.project_code_gaps)}</strong></div><div><span>Position gaps</span><strong>${escapeHtml(workflow.position_gaps)}</strong></div><div><span>Explicit Review rows</span><strong>${escapeHtml(workflow.review_rows)}</strong></div></div><div class="dataset-proof"><span><b>${escapeHtml(workflow.pdf_count)}</b> bank-statement PDFs supplied</span><span><b>${escapeHtml(workflow.matched_statement_files)}</b> filenames matched to account map</span><span><b>${escapeHtml(workflow.review_queue_rows)}</b> rows need attention</span></div>${exceptions ? `<div class="dataset-exceptions"><h4>Sample exception queue</h4>${exceptions}</div>` : ""}</article>`;
    }
    if (workflow.workflow === "investor_gl_to_loader") {
      return `<article class="dataset-workflow"><div class="dataset-head"><div><small>SPONSOR WORKFLOW 02</small><h3>${escapeHtml(workflow.title)}</h3><p>${escapeHtml(workflow.message)}</p></div><b class="dataset-status">${escapeHtml(workflowStatus(workflow.status))}</b></div><div class="dataset-metrics"><div><span>GL rows</span><strong>${Number(workflow.row_count || 0).toLocaleString("en-GB")}</strong></div><div><span>Columns</span><strong>${escapeHtml(workflow.column_count)}</strong></div><div><span>Legal entities</span><strong>${escapeHtml(workflow.legal_entity_count)}</strong></div><div><span>Investors</span><strong>${escapeHtml(workflow.investor_count)}</strong></div><div><span>Deals</span><strong>${escapeHtml(workflow.deal_count)}</strong></div><div><span>GL accounts</span><strong>${escapeHtml(workflow.gl_account_count)}</strong></div></div><div class="dataset-proof"><span>Loader sample ${workflow.loader_sample_supplied ? "supplied ✓" : "not supplied"}</span><span><b>${escapeHtml(workflow.transaction_type_count)}</b> transaction types</span><span><b>${escapeHtml(workflow.transaction_currency_count)}</b> transaction currencies</span></div></article>`;
    }
    if (workflow.workflow === "loader_target_contract") {
      return `<article class="dataset-workflow compact"><div class="dataset-head"><div><small>TARGET CONTRACT</small><h3>${escapeHtml(workflow.title)}</h3><p>${escapeHtml(workflow.workbook)}</p></div><b class="dataset-status">${escapeHtml(workflowStatus(workflow.status))}</b></div><div class="dataset-proof"><span><b>${escapeHtml(workflow.target_column_count)}</b> target columns</span><span>Required IDs ${workflow.required_target_fields_present ? "present ✓" : "need review"}</span></div></article>`;
    }
    return "";
  }).join("");
  container.innerHTML = `<div class="dataset-title"><p class="eyebrow">Auto-detected sponsor evidence</p><h2>Native Ylookup workflows, not a forced LP schema.</h2><p>${escapeHtml(result.message || "")}</p></div><div class="dataset-chips">${profileHtml}</div>${workflowHtml}`;
  container.classList.remove("hidden");
  renderBatchPicker([]);
}
async function tryYlookupDataset(pdfFiles, excelFiles, headers) {
  const form = new FormData();
  pdfFiles.forEach((file) => form.append("documents", file));
  excelFiles.forEach((file) => form.append("workbooks", file));
  const response = await fetch("/api/ylookup/analyse", { method: "POST", body: form, headers });
  let body = {};
  try { body = await response.json(); } catch { body = {}; }
  if (response.ok) return body;
  if (response.status === 422 && body.detail?.code === "not_ylookup_dataset") return null;
  throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message || `${response.status} ${response.statusText}`);
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
function resetEvidenceWorkspace() {
  state.case = null;
  state.batchCases = [];
  renderBatchPicker([]);
  $("#upload-form")?.reset();
  updateFileCounts();
  const datasetResults = $("#dataset-results");
  if (datasetResults) {
    datasetResults.innerHTML = "";
    datasetResults.classList.add("hidden");
  }
  $("#dashboard")?.classList.add("hidden");
  if ($("#download-review")) $("#download-review").disabled = true;
  $$('[data-scenario]').forEach((button) => button.classList.remove("active"));
  if ($("#upload-message")) {
    $("#upload-message").textContent = "Uploaded data and rendered analysis cleared. Select new evidence to start again.";
  }
}
async function clearUploadedMemory() {
  const confirmed = window.confirm("Clear selected files, rendered analysis and ephemeral server workflow memory?");
  if (!confirmed) return;
  const token = $("#upload-token")?.value.trim();
  const headers = token ? { "X-Cherry-Demo-Token": token } : {};
  loading(true);
  try {
    const result = await api("/api/session/clear-memory", { method: "POST", headers });
    resetEvidenceWorkspace();
    toast(`Memory cleared · ${result.cleared_workflow_records || 0} server workflow record${Number(result.cleared_workflow_records || 0) === 1 ? "" : "s"} removed.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(false);
  }
}
async function uploadEvidence(event) {
  event.preventDefault();
  const pdfFiles = [...$("#capital-call-input").files];
  const excelFiles = [...$("#commitments-input").files];
  const jsonFile = $("#cash-input").files[0] || null;
  if (!pdfFiles.length || !excelFiles.length) {
    toast("Select at least one PDF and one Excel workbook.", true);
    return;
  }
  const token = $("#upload-token")?.value.trim();
  const headers = token ? { "X-Cherry-Demo-Token": token } : {};
  $("#upload-message").textContent = `Detecting workflow for ${pdfFiles.length} PDF${pdfFiles.length === 1 ? "" : "s"} and ${excelFiles.length} workbook${excelFiles.length === 1 ? "" : "s"}…`;
  $("#dataset-results")?.classList.add("hidden");
  loading(true);
  try {
    const ylookupResult = await tryYlookupDataset(pdfFiles, excelFiles, headers);
    if (ylookupResult) {
      renderDatasetResults(ylookupResult);
      $("#upload-message").textContent = `Sponsor dataset detected: ${ylookupResult.workflows?.length || 0} workflow${(ylookupResult.workflows?.length || 0) === 1 ? "" : "s"} analysed without requiring an LP_Commitments sheet.`;
      $("#dataset-results").scrollIntoView({ behavior: "smooth", block: "start" });
      toast("Ylookup sponsor evidence analysed in its native workflow.");
      return;
    }

    const form = new FormData();
    pdfFiles.forEach((file) => form.append("capital_call", file));
    excelFiles.forEach((file) => form.append("commitments", file));
    if (jsonFile) form.append("fund_json", jsonFile);
    if ($("#as-of-input").value) form.append("as_of_date", $("#as-of-input").value);
    const cashMessage = jsonFile ? " with JSON cash evidence" : " without cash JSON";
    $("#upload-message").textContent = `Capital-call workflow detected. Processing ${pdfFiles.length} PDF${pdfFiles.length === 1 ? "" : "s"} and ${excelFiles.length} workbook${excelFiles.length === 1 ? "" : "s"}${cashMessage}…`;
    const result = await api("/api/private-markets/analyse-integrated", { method: "POST", body: form, headers });
    const cases = Array.isArray(result.cases) && result.cases.length ? result.cases : [result];
    renderBatchPicker(cases);
    renderCase({ ...cases[0], synthetic: false, transactions: [] });
    const batch = result.batch || { pdf_count: pdfFiles.length, excel_count: excelFiles.length, case_count: cases.length, json_count: jsonFile ? 1 : 0 };
    const cashSummary = batch.json_count ? "cash evidence included" : "cash evidence pending";
    $("#upload-message").textContent = `Batch ${result.batch_id || result.case_id}: ${batch.case_count} governed case${batch.case_count === 1 ? "" : "s"}; ${cashSummary}.`;
    $("#control-room").scrollIntoView({ behavior: "smooth" });
    toast(`${batch.case_count} capital-call case${batch.case_count === 1 ? "" : "s"} analysed · ${cashSummary}.`);
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
  $("#clear-upload-memory").addEventListener("click", clearUploadedMemory);
  $("#capital-call-input").addEventListener("change", updateFileCounts);
  $("#commitments-input").addEventListener("change", updateFileCounts);
  $("#batch-case-select").addEventListener("change", (event) => {
    const selected = state.batchCases[Number(event.target.value)];
    if (selected) renderCase({ ...selected, synthetic: false, transactions: [] });
  });
}
async function initialise() { bindEvents(); updateFileCounts(); await loadConfig(); await runScenario("exception", false); }
document.addEventListener("DOMContentLoaded", initialise);
