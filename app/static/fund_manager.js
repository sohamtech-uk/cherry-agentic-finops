(() => {
  "use strict";

  const state = {
    files: [],
    sources: null,
    analysis: null,
    busy: false,
  };

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

  const q = (selector, root = document) => root.querySelector(selector);
  const qa = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function notify(message, error = false) {
    if (typeof toast === "function") {
      toast(message, error);
      return;
    }
    // eslint-disable-next-line no-alert
    if (error) console.error(message);
  }

  function busy(visible) {
    state.busy = visible;
    if (typeof loading === "function") loading(visible);
  }

  function demoToken() {
    return q("#upload-token")?.value.trim() || "";
  }

  function injectStyles() {
    if (q('link[href="/static/fund_manager.css"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/fund_manager.css";
    document.head.appendChild(link);
  }

  function humanSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function typeLabel(detectedType) {
    if (TYPE_LABELS[detectedType]) return TYPE_LABELS[detectedType];
    if (detectedType === "unknown_workbook") return "Unknown workbook";
    if (detectedType === "unknown_pdf") return "Unknown document";
    if (detectedType === "unknown_json" || detectedType === "unknown_csv") return "Unknown data file";
    return "Unknown file";
  }

  function statusPill(status) {
    if (status === "processed") return '<span class="fm-pill ok">Identified</span>';
    if (status === "unreadable") return '<span class="fm-pill error">Unreadable</span>';
    return '<span class="fm-pill review">Needs review</span>';
  }

  function shellMarkup() {
    return `
<section class="fm-shell" id="fund-manager" aria-labelledby="fm-title">
  <div class="fm-inner">
    <div class="fm-head">
      <p class="fm-kicker">Cherry Fund Manager · NAV reconciliation</p>
      <h2 id="fm-title">Upload fund evidence.<br><em>Cherry works out what it is.</em></h2>
      <p>Add any mix of NAV workbooks, investor GLs, capital-call notices, LPAs, side letters, bank statements or position/cash/trade files. Cherry identifies each source before anything else happens — nothing here decides which controls to run yet.</p>
    </div>

    <div class="fm-card">
      <div class="fm-meta-grid">
        <label class="fm-field"><span>Fund / entity</span><input type="text" id="fm-fund-name" placeholder="Optional"></label>
        <label class="fm-field"><span>Reporting period</span><input type="text" id="fm-reporting-period" placeholder="Optional, e.g. Q2 2026"></label>
        <label class="fm-field"><span>As-of date</span><input type="date" id="fm-as-of-date"></label>
      </div>

      <div class="fm-dropzone" id="fm-dropzone">
        <strong>Add fund evidence</strong>
        <span>PDF · XLSX · CSV · JSON — drop files here or</span>
        <button type="button" class="fm-button secondary" id="fm-browse">Browse files</button>
        <small>Mixed file types in one review are fine. Nothing is required in advance.</small>
        <input type="file" id="fm-file-input" multiple accept=".pdf,.xlsx,.xls,.csv,.json">
      </div>

      <div class="fm-file-list" id="fm-file-list" aria-live="polite"></div>

      <div class="fm-actions">
        <button type="button" class="fm-button secondary" id="fm-classify" disabled>Identify sources</button>
        <button type="button" class="fm-button primary" id="fm-analyse" disabled>Analyse</button>
        <button type="button" class="fm-button ghost" id="fm-clear-files" hidden>Clear all</button>
        <span class="fm-file-count" id="fm-file-count"></span>
      </div>

      <div id="fm-inventory" aria-live="polite"></div>
      <div id="fm-analysis" aria-live="polite"></div>
    </div>
  </div>
</section>`;
  }

  function mountShell() {
    if (q("#fund-manager")) return;
    const sourceStrip = q(".source-strip");
    if (!sourceStrip) return;
    sourceStrip.insertAdjacentHTML("afterend", shellMarkup());
  }

  function renderFileList() {
    const list = q("#fm-file-list");
    const clearButton = q("#fm-clear-files");
    const classifyButton = q("#fm-classify");
    const analyseButton = q("#fm-analyse");
    const countLabel = q("#fm-file-count");
    if (!list) return;

    if (state.files.length === 0) {
      list.innerHTML = "";
      clearButton.hidden = true;
      classifyButton.disabled = true;
      analyseButton.disabled = true;
      countLabel.textContent = "";
      return;
    }

    list.innerHTML = state.files
      .map((file, index) => `
<div class="fm-file-row">
  <span class="fm-file-name" title="${esc(file.name)}">${esc(file.name)}</span>
  <span class="fm-file-size">${esc(humanSize(file.size))}</span>
  <button type="button" data-fm-remove="${index}" aria-label="Remove ${esc(file.name)}">✕</button>
</div>`)
      .join("");
    clearButton.hidden = false;
    classifyButton.disabled = state.busy;
    analyseButton.disabled = state.busy;
    countLabel.textContent = `${state.files.length} file${state.files.length === 1 ? "" : "s"} selected`;
  }

  function addFiles(fileList) {
    const incoming = [...fileList];
    const existingKeys = new Set(state.files.map((file) => `${file.name}:${file.size}`));
    for (const file of incoming) {
      const key = `${file.name}:${file.size}`;
      if (!existingKeys.has(key)) {
        state.files.push(file);
        existingKeys.add(key);
      }
    }
    renderFileList();
  }

  function renderInventory() {
    const target = q("#fm-inventory");
    if (!target) return;
    if (!state.sources) {
      target.innerHTML = "";
      return;
    }

    const { sources, source_count: sourceCount, unknown_count: unknownCount } = state.sources;
    if (sourceCount === 0) {
      target.innerHTML = '<div class="fm-empty">No sources identified yet.</div>';
      return;
    }

    const cards = sources
      .map((source) => {
        const label = typeLabel(source.detected_type);
        const cardClass = source.status === "processed" ? "" : ` ${esc(source.status)}`;
        const warnings = (source.warnings || [])
          .map((warning) => `<div class="fm-warning">${esc(warning)}</div>`)
          .join("");
        const hash = source.sha256 ? `${esc(source.sha256.slice(0, 10))}…` : "—";
        return `
<div class="fm-source-card${cardClass}">
  <div class="fm-source-icon">${esc(source.id.replace("SRC-", ""))}</div>
  <div class="fm-source-body">
    <strong title="${esc(source.filename)}">${esc(source.filename)}</strong>
    <p>${esc(label)}</p>
    ${warnings}
  </div>
  <div style="display:grid;gap:8px;justify-items:end;">
    ${statusPill(source.status)}
    <span class="fm-source-hash">${hash}</span>
  </div>
</div>`;
      })
      .join("");

    target.innerHTML = `
<div class="fm-inventory">
  <div class="fm-inventory-head">
    <h3>Evidence inventory</h3>
    <span>${esc(sourceCount)} file${sourceCount === 1 ? "" : "s"} · ${esc(unknownCount)} need${unknownCount === 1 ? "s" : ""} review</span>
  </div>
  <div class="fm-source-grid">${cards}</div>
  <div class="fm-boundary">Classification only identifies what was uploaded — it does not decide which controls to run or review the figures inside. No control has run yet.</div>
</div>`;
  }

  function buildEvidenceForm() {
    const form = new FormData();
    for (const file of state.files) form.append("files", file, file.name);
    const fundName = q("#fm-fund-name")?.value.trim();
    const reportingPeriod = q("#fm-reporting-period")?.value.trim();
    const asOfDate = q("#fm-as-of-date")?.value.trim();
    if (fundName) form.append("fund_name", fundName);
    if (reportingPeriod) form.append("reporting_period", reportingPeriod);
    if (asOfDate) form.append("as_of_date", asOfDate);
    return form;
  }

  async function postEvidence(path, form) {
    const headers = {};
    const token = demoToken();
    if (token) headers["X-Cherry-Demo-Token"] = token;

    const response = await fetch(path, { method: "POST", body: form, headers });
    let body = {};
    try { body = await response.json(); } catch { body = {}; }
    if (!response.ok) {
      const detail = typeof body.detail === "string"
        ? body.detail
        : body.detail?.message || `${response.status} ${response.statusText}`;
      throw new Error(detail);
    }
    return body;
  }

  async function classifySources() {
    if (state.files.length === 0 || state.busy) return;
    busy(true);
    try {
      const body = await postEvidence("/api/fund-manager/classify", buildEvidenceForm());
      state.sources = body;
      renderInventory();
      notify(`Identified ${body.source_count} source${body.source_count === 1 ? "" : "s"}.`);
    } catch (error) {
      notify(error.message || "Could not classify the uploaded files.", true);
    } finally {
      busy(false);
    }
  }

  async function runAnalysis() {
    if (state.files.length === 0 || state.busy) return;
    busy(true);
    try {
      const body = await postEvidence("/api/fund-manager/analyse", buildEvidenceForm());
      state.analysis = body;
      state.sources = { sources: body.sources, source_count: body.sources.length,
        unknown_count: body.sources.filter((s) => s.status !== "processed").length };
      renderInventory();
      renderAnalysis();
      notify(
        body.status === "clean"
          ? "Analysis complete — no issues found among the controls that ran."
          : `Analysis complete — ${body.issues_found} issue${body.issues_found === 1 ? "" : "s"} found.`,
        body.status !== "clean"
      );
    } catch (error) {
      notify(error.message || "Could not analyse the uploaded files.", true);
    } finally {
      busy(false);
    }
  }

  function severityPill(severity) {
    const label = severity.charAt(0).toUpperCase() + severity.slice(1);
    if (severity === "high") return `<span class="fm-pill error">${esc(label)}</span>`;
    if (severity === "medium") return `<span class="fm-pill review">${esc(label)}</span>`;
    return `<span class="fm-pill ok">${esc(label)}</span>`;
  }

  function controlPlanStatusPill(status) {
    if (status === "executed") return '<span class="fm-pill ok">Executed</span>';
    if (status === "needs_pairing") return '<span class="fm-pill review">Needs pairing</span>';
    return '<span class="fm-pill review">Not yet available</span>';
  }

  function renderAnalysis() {
    const target = q("#fm-analysis");
    if (!target) return;
    if (!state.analysis) {
      target.innerHTML = "";
      return;
    }

    const { status, issues_found: issuesFound, material, critical, issues, control_plan: plan } =
      state.analysis;
    const statusClass = status === "clean" ? "ok" : "review";
    const statusLabel = status === "clean" ? "Clean" : "Review required";

    const issueCards = (issues || [])
      .map((issue) => {
        const evidence = (issue.evidence || [])
          .map((item) => `<li>${esc(item.source)} — ${esc(item.detail)}</li>`)
          .join("");
        return `
<div class="fm-issue-card">
  <div class="fm-issue-head">
    <strong>${esc(issue.title)}</strong>
    ${severityPill(issue.severity)}
  </div>
  <p>${esc(issue.summary)}</p>
  ${evidence ? `<ul class="fm-issue-evidence">${evidence}</ul>` : ""}
  <p class="fm-issue-action"><strong>Recommended action:</strong> ${esc(issue.recommended_action)}</p>
</div>`;
      })
      .join("");

    const planRows = (plan || [])
      .map((entry) => `
<div class="fm-plan-row">
  <span class="fm-plan-file" title="${esc(entry.filename)}">${esc(entry.filename)}</span>
  <span class="fm-plan-control">${esc(entry.control)}</span>
  ${controlPlanStatusPill(entry.status)}
</div>`)
      .join("");

    target.innerHTML = `
<div class="fm-analysis">
  <div class="fm-qc-banner ${statusClass}">
    <div>
      <span class="fm-kicker">Fund administrator QC report</span>
      <strong>${esc(statusLabel)}</strong>
    </div>
    <div class="fm-qc-metrics">
      <div><span>Issues found</span><strong>${esc(issuesFound)}</strong></div>
      <div><span>Material</span><strong>${esc(material)}</strong></div>
      <div><span>Critical</span><strong>${esc(critical)}</strong></div>
    </div>
  </div>
  ${issueCards ? `<div class="fm-issue-grid">${issueCards}</div>` : '<div class="fm-empty">No issues from the controls that ran.</div>'}
  <details class="fm-control-plan">
    <summary>Control plan (${(plan || []).length} recognised source${(plan || []).length === 1 ? "" : "s"})</summary>
    <div class="fm-plan-grid">${planRows}</div>
  </details>
  <div class="fm-boundary">Deterministic tools produced every figure and comparison above; no LLM decided a pass/fail. Controls marked "not yet available" never ran — they are not silent passes.</div>
</div>`;
  }

  function wireEvents() {
    const dropzone = q("#fm-dropzone");
    const input = q("#fm-file-input");
    const browseButton = q("#fm-browse");

    browseButton?.addEventListener("click", () => input?.click());
    input?.addEventListener("change", (event) => {
      addFiles(event.target.files);
      event.target.value = "";
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone?.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      dropzone?.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove("dragover");
      });
    });
    dropzone?.addEventListener("drop", (event) => {
      if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
    });

    q("#fm-file-list")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-fm-remove]");
      if (!button) return;
      const index = Number(button.dataset.fmRemove);
      state.files.splice(index, 1);
      renderFileList();
    });

    q("#fm-clear-files")?.addEventListener("click", () => {
      state.files = [];
      state.sources = null;
      state.analysis = null;
      renderFileList();
      renderInventory();
      renderAnalysis();
    });

    q("#fm-classify")?.addEventListener("click", classifySources);
    q("#fm-analyse")?.addEventListener("click", runAnalysis);
  }

  function addNavLink() {
    const nav = q(".primary-nav");
    if (!nav || q('a[href="#fund-manager"]', nav)) return;
    nav.insertAdjacentHTML("afterbegin", '<a href="#fund-manager"><strong>Fund Manager</strong></a>');
  }

  function init() {
    injectStyles();
    mountShell();
    addNavLink();
    wireEvents();
    renderFileList();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
