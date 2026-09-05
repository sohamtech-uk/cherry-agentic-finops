(() => {
  "use strict";

  const TEMPLATE_KEY = "cherry-nav-control-manager-template-v1";
  const runtime = {
    reconciliation: null,
    statement: null,
    contract: null,
    humanPrepared: false,
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
    const node = q("#toast");
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("error", error);
    node.classList.add("visible");
    setTimeout(() => node.classList.remove("visible"), 3500);
  }

  function busy(visible) {
    if (typeof loading === "function") loading(visible);
  }

  function demoToken() {
    return q("#upload-token")?.value.trim() || "";
  }

  async function requestJson(path, options = {}) {
    const response = await fetch(path, options);
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

  function injectStyles() {
    if (q('link[href="/static/nav_manager.css"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/nav_manager.css";
    document.head.appendChild(link);
  }

  function workspaceMarkup() {
    return `
<section class="navm-shell" id="nav-manager" aria-labelledby="navm-title">
  <div class="navm-inner">
    <div class="navm-head">
      <div>
        <p class="navm-kicker">Supervisor workspace · NAV quality control</p>
        <h2 id="navm-title">Define the review once.<br><em>Run it with governed agents.</em></h2>
        <p class="navm-head-copy">The fund manager defines the control policy. The <strong>NAV Control Manager</strong> routes each stage to a specialist with a restricted toolset, consolidates exceptions and stops at a human decision gate.</p>
      </div>
      <aside class="navm-supervisor-note">
        <span>Supervisor active</span>
        <strong>LLM chooses the specialist and tool.</strong>
        <p>The selected tool retrieves, compares or calculates. Deterministic controls produce the finding. No agent gets payment authority.</p>
      </aside>
    </div>

    <div class="navm-commandbar" aria-label="NAV Control Manager workspace navigation">
      <div class="navm-tabs" role="tablist">
        <button class="navm-tab active" type="button" data-navm-tab="overview">Overview</button>
        <button class="navm-tab" type="button" data-navm-tab="workflow">Workflow builder</button>
        <button class="navm-tab" type="button" data-navm-tab="agents">Agent workspaces</button>
        <button class="navm-tab" type="button" data-navm-tab="review">Review pack</button>
      </div>
      <div class="navm-command-actions">
        <button class="navm-small-button" id="navm-open-upload" type="button">Use uploaded evidence</button>
        <button class="navm-small-button primary" id="navm-configure" type="button">Configure workflow →</button>
      </div>
    </div>

    <div class="navm-view" data-navm-view="overview">
      <div class="navm-overview-grid">
        <article class="navm-card">
          <header class="navm-card-head">
            <div><small>Current template</small><h3 id="navm-template-title">Quarterly NAV Review</h3></div>
            <span class="navm-status-pill" id="navm-workflow-status">Ready to run</span>
          </header>
          <div class="navm-workflow-pipeline" aria-label="NAV review pipeline">
            <div class="navm-stage" data-stage="statement">
              <div class="navm-stage-index">01</div><span>Evidence</span><h4>Statement Agent</h4><p>Compare periods, sections, entities and dates.</p><b class="navm-stage-state" id="navm-stage-statement">Ready</b>
            </div>
            <div class="navm-stage" data-stage="contract">
              <div class="navm-stage-index">02</div><span>Rules</span><h4>Contract Agent</h4><p>Resolve source-backed fund and investor terms.</p><b class="navm-stage-state" id="navm-stage-contract">Ready</b>
            </div>
            <div class="navm-stage" data-stage="reconciliation">
              <div class="navm-stage-index">03</div><span>Numbers</span><h4>Reconciliation Agent</h4><p>Foot, bridge and compare the NAV evidence.</p><b class="navm-stage-state" id="navm-stage-reconciliation">Ready</b>
            </div>
            <div class="navm-stage" data-stage="exception">
              <div class="navm-stage-index">04</div><span>Triage</span><h4>Exception Agent</h4><p>Group breaks, materiality and dependencies.</p><b class="navm-stage-state" id="navm-stage-exception">Watching queues</b>
            </div>
            <div class="navm-stage human" data-stage="human">
              <div class="navm-stage-index">05</div><span>Decision</span><h4>Human review</h4><p>Approve, return or request evidence after controls.</p><b class="navm-stage-state" id="navm-stage-human">Required</b>
            </div>
          </div>
        </article>

        <aside class="navm-card navm-policy-card">
          <header class="navm-card-head"><div><small>Fund manager policy</small><h3>Control envelope</h3></div><span class="navm-status-pill">Session</span></header>
          <div class="navm-policy-list">
            <div class="navm-policy-row"><span>Tolerance</span><strong id="navm-policy-tolerance">£0.01</strong></div>
            <div class="navm-policy-row"><span>Materiality</span><strong id="navm-policy-materiality">£25,000</strong></div>
            <div class="navm-policy-row"><span>Ambiguity</span><strong id="navm-policy-ambiguity">Stop & review</strong></div>
            <div class="navm-policy-row"><span>Source evidence</span><strong id="navm-policy-source">Required</strong></div>
            <div class="navm-policy-row"><span>Human gate</span><strong id="navm-policy-human">Required</strong></div>
          </div>
          <p class="navm-boundary-note">The template is a browser-session control policy. It does not silently change legal terms, accounting records or payment permissions.</p>
        </aside>
      </div>

      <div class="navm-live-grid" aria-label="Live specialist status">
        <div class="navm-live-card"><span>Reconciliation</span><strong id="navm-live-reconciliation">Ready</strong><small id="navm-live-reconciliation-note">Run the NAV review or inspect the live control room.</small></div>
        <div class="navm-live-card"><span>Contract rules</span><strong id="navm-live-contract">Ready</strong><small id="navm-live-contract-note">Source-linked rule resolution; synthetic demo remains labelled.</small></div>
        <div class="navm-live-card"><span>Statement evidence</span><strong id="navm-live-statement">Ready</strong><small id="navm-live-statement-note">Current/prior document comparison is available.</small></div>
        <div class="navm-live-card"><span>Exceptions</span><strong id="navm-live-exceptions">0 surfaced</strong><small id="navm-live-exceptions-note">Current control and sponsor queues are monitored.</small></div>
      </div>

      <div class="navm-flow-boundary" aria-label="Control boundary">
        <div><span>01 Supervisor</span><strong>Selects specialist</strong></div>
        <div><span>02 Specialist</span><strong>Selects whitelisted tool</strong></div>
        <div><span>03 Tool</span><strong>Retrieves / calculates facts</strong></div>
        <div><span>04 Control</span><strong>Pass / review / stop</strong></div>
        <div><span>05 Exception</span><strong>Groups & routes breaks</strong></div>
        <div><span>06 Human</span><strong>Makes final decision</strong></div>
      </div>
    </div>

    <div class="navm-view" data-navm-view="workflow" hidden>
      <div class="navm-builder-grid">
        <article class="navm-card navm-form-card">
          <h3>Fund manager policy</h3>
          <p>Configure business controls, not prompts. Saved values stay only in this browser session.</p>
          <form id="navm-workflow-form">
            <div class="navm-form-grid">
              <label class="navm-field full"><span>Template name</span><input id="navm-template-name" value="Quarterly NAV Review" maxlength="80"></label>
              <label class="navm-field"><span>Fund / entity</span><input id="navm-fund-name" placeholder="Fund A"></label>
              <label class="navm-field"><span>Reporting period</span><input id="navm-period" placeholder="Q2 2026"></label>
              <label class="navm-field"><span>Monetary tolerance</span><input id="navm-tolerance" type="number" min="0" step="0.01" value="0.01"></label>
              <label class="navm-field"><span>Materiality threshold</span><input id="navm-materiality" type="number" min="0" step="100" value="25000"></label>
            </div>
            <div class="navm-switches">
              <label class="navm-switch"><div><strong>Stop on ambiguous evidence</strong><small>Never let uncertainty auto-pass.</small></div><input id="navm-stop-ambiguity" type="checkbox" checked></label>
              <label class="navm-switch"><div><strong>Require source locators</strong><small>Rules and findings must link to evidence.</small></div><input id="navm-require-source" type="checkbox" checked></label>
              <label class="navm-switch"><div><strong>Human approval gate</strong><small>Final release remains a human decision.</small></div><input id="navm-human-required" type="checkbox" checked></label>
            </div>
            <div class="navm-form-actions">
              <button class="navm-small-button primary" type="submit">Save session template</button>
              <button class="navm-small-button" id="navm-reset-template" type="button">Reset defaults</button>
            </div>
            <p class="navm-session-note">No upload token, document text or financial evidence is stored in this session template.</p>
          </form>
        </article>

        <article class="navm-card navm-stage-builder">
          <h3>Review sequence</h3>
          <p>Enable the specialist stages needed for this fund. Any failed specialist stage routes into the exception queue before the human gate.</p>
          <div class="navm-builder-stages">
            <div class="navm-builder-stage"><span>01</span><div><strong>Statement Agent</strong><small>Current vs prior period · sections · entities · dates</small></div><label><input type="checkbox" data-navm-stage-toggle="statement" checked> Enabled</label></div>
            <div class="navm-builder-stage"><span>02</span><div><strong>Contract Agent</strong><small>LPA default · side-letter override · effective date</small></div><label><input type="checkbox" data-navm-stage-toggle="contract" checked> Enabled</label></div>
            <div class="navm-builder-stage"><span>03</span><div><strong>Reconciliation Agent</strong><small>Footing · bridge · ledger comparison · investor capital</small></div><label><input type="checkbox" data-navm-stage-toggle="reconciliation" checked> Enabled</label></div>
            <div class="navm-builder-stage"><span>04</span><div><strong>Exception Agent</strong><small>Related breaks · materiality · dependency path · owner</small></div><label><input type="checkbox" data-navm-stage-toggle="exception" checked> Enabled</label></div>
            <div class="navm-builder-stage human"><span>05</span><div><strong>Human fund-manager gate</strong><small>Approve / return / request evidence after specialist controls</small></div><label><input type="checkbox" data-navm-stage-toggle="human" checked disabled> Required</label></div>
          </div>
          <div class="navm-form-actions">
            <button class="navm-small-button primary" id="navm-use-template" type="button">Use template in this session →</button>
            <button class="navm-small-button" id="navm-jump-agents" type="button">Open specialist workspaces</button>
          </div>
        </article>
      </div>
    </div>

    <div class="navm-view" data-navm-view="agents" hidden>
      <div class="navm-agent-grid">
        <article class="navm-card navm-agent-card" id="reconciliation-manager">
          <header class="navm-card-head"><div><small>Specialist 01 · financial controls</small><h3>Reconciliation Manager</h3></div><span class="navm-agent-badge">Live restricted tools</span></header>
          <div class="navm-agent-body">
            <p class="navm-agent-copy">The LLM may choose only the reconciliation primitives below for ad-hoc accounting work. The tools perform reads, sums, comparisons and bridges; the model does not invent the arithmetic.</p>
            <p class="navm-tool-label">Permitted specialist tools</p>
            <div class="navm-tools"><code class="navm-tool">read_excel()</code><code class="navm-tool">read_cell()</code><code class="navm-tool">calculate_sum()</code><code class="navm-tool">compare_values()</code><code class="navm-tool">build_bridge()</code><code class="navm-tool">query_database()</code></div>
            <p class="navm-agent-rule">Packaged NAV checks can orchestrate these controls in one deterministic review. The service recommends an action but never posts a correcting journal or changes the official NAV.</p>

            <form class="navm-inline-form" id="navm-recon-form">
              <div class="navm-form-grid">
                <label class="navm-field full"><span>Administrator NAV summary · JSON *</span><input id="navm-nav-summary" type="file" accept=".json,application/json" required></label>
                <label class="navm-field"><span>Source investor GL · XLSX</span><input id="navm-source-ledger" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"></label>
                <label class="navm-field"><span>Structured side-letter rules · JSON</span><input id="navm-side-rules" type="file" accept=".json,application/json"></label>
              </div>
              <label class="navm-switch"><div><strong>Resolve rules from already-ingested contract documents</strong><small>Mutually exclusive with an uploaded side-letter rules JSON.</small></div><input id="navm-use-contract-docs" type="checkbox"></label>
              <div class="navm-agent-actions"><button class="navm-small-button primary" type="submit">Run deterministic NAV review →</button><button class="navm-small-button" id="navm-open-control-room" type="button">Open live control room</button></div>
            </form>
            <div class="navm-inline-result" id="navm-recon-result" hidden></div>
          </div>
        </article>

        <article class="navm-card navm-agent-card" id="contract-manager">
          <header class="navm-card-head"><div><small>Specialist 02 · governing rules</small><h3>Contract Manager</h3></div><span class="navm-agent-badge">Live restricted tools</span></header>
          <div class="navm-agent-body">
            <p class="navm-agent-copy">Search and resolve operational rules only from source-backed contract evidence. Missing, conflicting or not-yet-effective terms route to review rather than being guessed.</p>
            <p class="navm-tool-label">Permitted specialist tools</p>
            <div class="navm-tools"><code class="navm-tool">search_lpa()</code><code class="navm-tool">search_side_letter()</code><code class="navm-tool">extract_clause()</code><code class="navm-tool">get_effective_date()</code><code class="navm-tool">get_investor_rule()</code></div>
            <p class="navm-agent-rule"><strong>Hackathon provenance:</strong> the sponsor pack has no real LPA or side letter. The judge-facing fee example therefore remains a clearly labelled synthetic, context-derived demo.</p>
            <div class="navm-agent-actions"><button class="navm-small-button primary" id="navm-contract-demo" type="button">Run synthetic side-letter control →</button><button class="navm-small-button" id="navm-open-contracts" type="button">Open full rule bridge</button></div>
            <div class="navm-inline-result" id="navm-contract-result" hidden></div>
          </div>
        </article>

        <article class="navm-card navm-agent-card" id="statement-agent">
          <header class="navm-card-head"><div><small>Specialist 03 · document review</small><h3>Statement Agent</h3></div><span class="navm-agent-badge">Live restricted tools</span></header>
          <div class="navm-agent-body">
            <p class="navm-agent-copy">Compare the current statement with prior-period evidence and surface exact text/date/entity differences. A match is evidence for review, not an automatic legal or accounting conclusion.</p>
            <p class="navm-tool-label">Permitted specialist tools</p>
            <div class="navm-tools"><code class="navm-tool">read_document()</code><code class="navm-tool">compare_periods()</code><code class="navm-tool">find_section()</code><code class="navm-tool">find_entity()</code><code class="navm-tool">compare_dates()</code></div>
            <form class="navm-inline-form" id="navm-statement-form">
              <div class="navm-form-grid">
                <label class="navm-field"><span>Current statement · PDF/TXT/MD *</span><input id="navm-current-statement" type="file" accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown" required></label>
                <label class="navm-field"><span>Prior statement · optional</span><input id="navm-prior-statement" type="file" accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"></label>
                <label class="navm-field"><span>Section to locate</span><input id="navm-section-heading" placeholder="Subsequent Events"></label>
                <label class="navm-field"><span>Entity to trace</span><input id="navm-entity-name" placeholder="Portfolio company or investor"></label>
              </div>
              <div class="navm-agent-actions"><button class="navm-small-button primary" type="submit">Compare statement evidence →</button><button class="navm-small-button" id="navm-open-upload-from-statement" type="button">Open general evidence upload</button></div>
            </form>
            <div class="navm-inline-result" id="navm-statement-result" hidden></div>
          </div>
        </article>

        <article class="navm-card navm-agent-card" id="exception-agent">
          <header class="navm-card-head"><div><small>Specialist 04 · dependency-aware triage</small><h3>Exception Manager</h3></div><span class="navm-agent-badge planned">Tool contract · next backend slice</span></header>
          <div class="navm-agent-body">
            <p class="navm-agent-copy">The current product already has live control-room and sponsor exception queues. The dedicated dependency-aware Exception Agent tool contract below is shown separately so the UI does not pretend those four orchestration tools are already implemented.</p>
            <p class="navm-tool-label">Restricted exception orchestration contract</p>
            <div class="navm-tools"><code class="navm-tool">query_exceptions()</code><code class="navm-tool">group_related_errors()</code><code class="navm-tool">calculate_materiality()</code><code class="navm-tool">trace_dependency()</code></div>
            <p class="navm-agent-rule">Target behavior: many row-level errors → related groups → material root causes → dependency path → owned next-best work. Human review remains mandatory for ambiguous resolution.</p>
            <div class="navm-live-grid" style="grid-template-columns:1fr 1fr;margin-top:14px">
              <div class="navm-live-card"><span>Control-room queue</span><strong id="navm-exception-control-count">0</strong><small>Open next-best work items</small></div>
              <div class="navm-live-card"><span>Sponsor queue</span><strong id="navm-exception-sponsor-count">0</strong><small>Workbook exceptions after analysis</small></div>
            </div>
            <div class="navm-agent-actions"><button class="navm-small-button primary" id="navm-open-exceptions" type="button">Open current exception queue →</button><button class="navm-small-button" id="navm-open-sponsor-exceptions" type="button">Open sponsor queue</button></div>
          </div>
        </article>
      </div>
    </div>

    <div class="navm-view" data-navm-view="review" hidden>
      <div class="navm-review-grid">
        <article class="navm-card navm-review-main">
          <header class="navm-card-head"><div><small>Supervisor consolidation</small><h3>Review pack readiness</h3></div><span class="navm-status-pill warning" id="navm-review-status">Evidence in progress</span></header>
          <div class="navm-review-summary">
            <div><span>Specialists touched</span><strong id="navm-review-agents">0 / 3</strong><small>Live specialist runs in this session</small></div>
            <div><span>Controls passed</span><strong id="navm-review-controls">—</strong><small>From latest deterministic NAV review</small></div>
            <div><span>Exceptions</span><strong id="navm-review-exceptions">0</strong><small>Live queues currently surfaced</small></div>
            <div><span>Human gate</span><strong id="navm-review-human">Required</strong><small>No silent approval</small></div>
          </div>
          <div class="navm-review-log" id="navm-review-log"></div>
          <div class="navm-form-actions" style="padding:0 19px">
            <button class="navm-small-button primary" id="navm-prepare-review" type="button">Prepare for human review</button>
            <button class="navm-small-button" id="navm-download-manifest" type="button">Download session manifest ↓</button>
            <button class="navm-small-button" id="navm-open-reports" type="button">Open PDF / Excel reports</button>
          </div>
        </article>

        <aside class="navm-card navm-human-gate">
          <header class="navm-card-head"><div><small>Final boundary</small><h3>Fund-manager gate</h3></div><span class="navm-status-pill warning">Human only</span></header>
          <div class="navm-human-gate-body">
            <div class="navm-gate-icon">✓</div>
            <h4>Decision authority stays outside the LLM.</h4>
            <p>Cherry can prepare evidence, recommended actions and review packs. This workspace does not infer consent, amend the official NAV or initiate a payment.</p>
            <div class="navm-gate-state" id="navm-gate-state">Awaiting specialist evidence</div>
          </div>
        </aside>
      </div>
    </div>
  </div>
</section>`;
  }

  function mountWorkspace() {
    if (q("#nav-manager")) return;
    const sourceStrip = q(".source-strip");
    if (!sourceStrip) return;
    sourceStrip.insertAdjacentHTML("afterend", workspaceMarkup());
  }

  function showView(name) {
    qa("[data-navm-view]").forEach((view) => { view.hidden = view.dataset.navmView !== name; });
    qa("[data-navm-tab]").forEach((tab) => tab.classList.toggle("active", tab.dataset.navmTab === name));
  }

  function wirePrimaryNav() {
    const dropdown = q(".nav-dropdown-menu");
    if (!dropdown) return;
    const targets = {
      "Reconciliation Manager": "#reconciliation-manager",
      "Contract Manager": "#contract-manager",
      "Statement Agent": "#statement-agent",
      "Exception Manager": "#exception-agent",
    };
    qa("a", dropdown).forEach((link) => {
      const label = q("strong", link)?.textContent.trim();
      if (targets[label]) link.href = targets[label];
    });
    if (!q(".navm-supervisor-link", dropdown)) {
      dropdown.insertAdjacentHTML("afterbegin", '<a class="navm-supervisor-link" href="#nav-manager"><strong>Supervisor workspace</strong><small>Define policy, sequence agents and prepare review</small></a>');
    }
    qa('a[href^="#"]', dropdown).forEach((link) => {
      link.addEventListener("click", (event) => {
        const href = link.getAttribute("href");
        if (!href) return;
        if (["#reconciliation-manager", "#contract-manager", "#statement-agent", "#exception-agent"].includes(href)) {
          event.preventDefault();
          showView("agents");
          q(".nav-dropdown")?.removeAttribute("open");
          requestAnimationFrame(() => q(href)?.scrollIntoView({ behavior: "smooth", block: "start" }));
        } else if (href === "#nav-manager") {
          q(".nav-dropdown")?.removeAttribute("open");
        }
      });
    });
  }

  function currentPolicy() {
    return {
      name: q("#navm-template-name")?.value.trim() || "Quarterly NAV Review",
      fund: q("#navm-fund-name")?.value.trim() || "",
      period: q("#navm-period")?.value.trim() || "",
      tolerance: q("#navm-tolerance")?.value || "0.01",
      materiality: q("#navm-materiality")?.value || "25000",
      stop_on_ambiguity: Boolean(q("#navm-stop-ambiguity")?.checked),
      require_source_locator: Boolean(q("#navm-require-source")?.checked),
      human_gate_required: true,
      stages: Object.fromEntries(qa("[data-navm-stage-toggle]").map((input) => [input.dataset.navmStageToggle, Boolean(input.checked)])),
    };
  }

  function formatMoneyNumber(value) {
    const number = Number(value || 0);
    return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 2 }).format(number);
  }

  function applyPolicy(policy) {
    if (!policy) return;
    if (q("#navm-template-name")) q("#navm-template-name").value = policy.name || "Quarterly NAV Review";
    if (q("#navm-fund-name")) q("#navm-fund-name").value = policy.fund || "";
    if (q("#navm-period")) q("#navm-period").value = policy.period || "";
    if (q("#navm-tolerance")) q("#navm-tolerance").value = policy.tolerance ?? "0.01";
    if (q("#navm-materiality")) q("#navm-materiality").value = policy.materiality ?? "25000";
    if (q("#navm-stop-ambiguity")) q("#navm-stop-ambiguity").checked = policy.stop_on_ambiguity !== false;
    if (q("#navm-require-source")) q("#navm-require-source").checked = policy.require_source_locator !== false;
    Object.entries(policy.stages || {}).forEach(([name, enabled]) => {
      const input = q(`[data-navm-stage-toggle="${name}"]`);
      if (input && name !== "human") input.checked = Boolean(enabled);
    });
    updatePolicyUi();
  }

  function updatePolicyUi() {
    const policy = currentPolicy();
    q("#navm-template-title").textContent = policy.name;
    q("#navm-policy-tolerance").textContent = formatMoneyNumber(policy.tolerance);
    q("#navm-policy-materiality").textContent = formatMoneyNumber(policy.materiality);
    q("#navm-policy-ambiguity").textContent = policy.stop_on_ambiguity ? "Stop & review" : "Continue with warning";
    q("#navm-policy-source").textContent = policy.require_source_locator ? "Required" : "Optional";
    q("#navm-policy-human").textContent = "Required";
    Object.entries(policy.stages).forEach(([stage, enabled]) => {
      const node = q(`#navm-stage-${stage}`);
      if (!node || stage === "human") return;
      if (!enabled) {
        node.textContent = "Disabled by template";
        node.classList.add("review");
      } else if (!runtime[stage] && stage !== "exception") {
        node.textContent = "Ready";
        node.classList.remove("review");
      }
    });
  }

  function loadPolicy() {
    try {
      const raw = sessionStorage.getItem(TEMPLATE_KEY);
      if (raw) applyPolicy(JSON.parse(raw));
      else updatePolicyUi();
    } catch {
      updatePolicyUi();
    }
  }

  function savePolicy(event) {
    event?.preventDefault();
    const policy = currentPolicy();
    sessionStorage.setItem(TEMPLATE_KEY, JSON.stringify(policy));
    updatePolicyUi();
    q("#navm-workflow-status").textContent = "Template saved";
    notify(`${policy.name} saved for this browser session.`);
  }

  function resetPolicy() {
    sessionStorage.removeItem(TEMPLATE_KEY);
    applyPolicy({
      name: "Quarterly NAV Review",
      fund: "",
      period: "",
      tolerance: "0.01",
      materiality: "25000",
      stop_on_ambiguity: true,
      require_source_locator: true,
      stages: { statement: true, contract: true, reconciliation: true, exception: true, human: true },
    });
    notify("Workflow template reset to governed defaults.");
  }

  function renderReconciliationResult(payload) {
    const review = payload.review || {};
    const findings = review.findings || [];
    const workItems = review.work_items || [];
    const result = q("#navm-recon-result");
    const actionLabel = String(review.action || "review").replaceAll("_", " ");
    const topFindings = findings.slice(0, 8).map((item) => `<div class="navm-mini-item ${esc(item.severity)}"><strong>${esc(item.title)}</strong><p>${esc(item.detail)}${item.expected || item.observed ? `<br>${item.expected ? `Expected ${esc(item.expected)}` : ""}${item.expected && item.observed ? " · " : ""}${item.observed ? `Observed ${esc(item.observed)}` : ""}` : ""}</p></div>`).join("");
    const tasks = workItems.slice(0, 5).map((item) => `<div class="navm-mini-item"><strong>${esc(item.owner)} · ${esc(item.title)}</strong><p>${esc(item.instruction)}</p></div>`).join("");
    result.innerHTML = `<div class="navm-result-head"><div><small>${esc(payload.case_id || "NAV review")}</small><strong>${esc(payload.legal_entity || review.legal_entity || "NAV quality review")}</strong></div><span class="navm-status-pill ${review.action === "ready_to_submit" ? "" : "review"}">${esc(actionLabel)}</span></div><div class="navm-result-content"><div class="navm-result-metrics"><div><span>Controls passed</span><strong>${esc(review.controls_passed ?? 0)}</strong></div><div><span>Exceptions open</span><strong>${esc(review.exceptions_open ?? 0)}</strong></div><div><span>Period</span><strong>${esc(review.period_end || "—")}</strong></div></div><div class="navm-mini-list">${topFindings || '<div class="navm-mini-item"><strong>No findings returned</strong></div>'}${tasks ? `<div class="navm-mini-item"><strong>Owned work</strong><p>${workItems.length} work item${workItems.length === 1 ? "" : "s"} routed for follow-up.</p></div>${tasks}` : ""}</div></div>`;
    result.hidden = false;
    runtime.reconciliation = payload;
    q("#navm-stage-reconciliation").textContent = review.action === "ready_to_submit" ? "Passed" : `${review.exceptions_open || 0} exception${review.exceptions_open === 1 ? "" : "s"}`;
    q("#navm-stage-reconciliation").classList.toggle("review", review.action !== "ready_to_submit");
    syncSupervisor();
  }

  async function runReconciliation(event) {
    event.preventDefault();
    const summary = q("#navm-nav-summary")?.files[0];
    if (!summary) { notify("Select an administrator NAV summary JSON.", true); return; }
    const ledger = q("#navm-source-ledger")?.files[0];
    const rules = q("#navm-side-rules")?.files[0];
    const useContracts = Boolean(q("#navm-use-contract-docs")?.checked);
    if (rules && useContracts) { notify("Choose source-backed contract documents or a rules JSON, not both.", true); return; }
    const form = new FormData();
    form.append("nav_summary", summary);
    if (ledger) form.append("source_ledger", ledger);
    if (rules) form.append("side_letter_rules", rules);
    form.append("use_contract_documents", useContracts ? "true" : "false");
    const token = demoToken();
    const headers = token ? { "X-Cherry-Demo-Token": token } : {};
    busy(true);
    try {
      const payload = await requestJson("/api/nav-quality/review", { method: "POST", body: form, headers });
      renderReconciliationResult(payload);
      notify(`NAV review complete · ${payload.review?.controls_passed || 0} controls passed.`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      busy(false);
    }
  }

  function renderStatementResult(payload) {
    const result = q("#navm-statement-result");
    const sourceCount = payload.evidence?.sources?.length || 1;
    const added = payload.period_diff?.lines_added?.length || 0;
    const removed = payload.period_diff?.lines_removed?.length || 0;
    const sameDates = payload.date_diff?.dates_in_both?.length || 0;
    const section = payload.section;
    const entity = payload.entity;
    const evidenceRows = [
      section ? `<div class="navm-mini-item ${section.found ? "" : "warning"}"><strong>Section ${section.found ? "located" : "not located"}: ${esc(section.heading)}</strong><p>${section.found ? `Lines ${esc(section.start_line)}–${esc(section.end_line)} surfaced for semantic review.` : "A different heading may be used; this is not proof of absence."}</p></div>` : "",
      entity ? `<div class="navm-mini-item"><strong>Entity matches: ${esc(entity.occurrences)}</strong><p>${esc(entity.entity)} · exact text occurrences returned by the tool.</p></div>` : "",
      payload.period_diff ? `<div class="navm-mini-item"><strong>Period diff</strong><p>${added} line${added === 1 ? "" : "s"} added · ${removed} removed · ${payload.period_diff.identical ? "documents text-identical" : "changes surfaced"}.</p></div>` : "",
      payload.date_diff ? `<div class="navm-mini-item"><strong>Date comparison</strong><p>${sameDates} date${sameDates === 1 ? "" : "s"} occur in both periods. Unchanged dates are review candidates, not automatically defects.</p></div>` : "",
    ].filter(Boolean).join("");
    result.innerHTML = `<div class="navm-result-head"><div><small>Statement evidence</small><strong>${esc(payload.current_document?.document || "Current statement")}</strong></div><span class="navm-status-pill">Evidence surfaced</span></div><div class="navm-result-content"><div class="navm-result-metrics"><div><span>Sources</span><strong>${sourceCount}</strong></div><div><span>Lines added</span><strong>${added}</strong></div><div><span>Dates in both</span><strong>${sameDates}</strong></div></div><div class="navm-mini-list">${evidenceRows || '<div class="navm-mini-item"><strong>Document read</strong><p>No optional comparison target was requested.</p></div>'}</div></div>`;
    result.hidden = false;
    runtime.statement = payload;
    q("#navm-stage-statement").textContent = "Evidence surfaced";
    q("#navm-stage-statement").classList.remove("review");
    syncSupervisor();
  }

  async function runStatement(event) {
    event.preventDefault();
    const current = q("#navm-current-statement")?.files[0];
    if (!current) { notify("Select a current-period statement.", true); return; }
    const form = new FormData();
    form.append("current_document", current);
    const prior = q("#navm-prior-statement")?.files[0];
    if (prior) form.append("prior_document", prior);
    const section = q("#navm-section-heading")?.value.trim();
    const entity = q("#navm-entity-name")?.value.trim();
    if (section) form.append("section_heading", section);
    if (entity) form.append("entity_name", entity);
    const token = demoToken();
    const headers = token ? { "X-Cherry-Demo-Token": token } : {};
    busy(true);
    try {
      const payload = await requestJson("/api/statement-review/compare", { method: "POST", body: form, headers });
      renderStatementResult(payload);
      notify("Statement evidence compared with deterministic document tools.");
    } catch (error) {
      notify(error.message, true);
    } finally {
      busy(false);
    }
  }

  function renderContractCompact(payload) {
    const analysis = payload.analysis || {};
    const finding = (analysis.findings || []).find((item) => item.code === "SIDE_LETTER_FEE_OVERRIDE_NOT_APPLIED") || (analysis.findings || [])[0];
    const result = q("#navm-contract-result");
    result.innerHTML = `<div class="navm-result-head"><div><small>Context-derived synthetic demo</small><strong>${esc(analysis.fund_name || "Cherry Contract Agent")}</strong></div><span class="navm-status-pill review">${esc(String(analysis.decision || "review_required").replaceAll("_", " "))}</span></div><div class="navm-result-content"><div class="navm-result-metrics"><div><span>Rules extracted</span><strong>${esc(analysis.rules_extracted ?? 0)}</strong></div><div><span>Non-standard investors</span><strong>${esc(analysis.non_standard_investor_count ?? 0)}</strong></div><div><span>Potential overcall</span><strong>${formatMoneyNumber(analysis.potential_overcall || 0)}</strong></div></div>${finding ? `<div class="navm-mini-item high"><strong>${esc(finding.title)}</strong><p>${esc(finding.detail)}</p></div>` : ""}</div>`;
    result.hidden = false;
    runtime.contract = payload;
    q("#navm-stage-contract").textContent = analysis.decision === "pass" ? "Passed" : "Review required";
    q("#navm-stage-contract").classList.toggle("review", analysis.decision !== "pass");
    syncSupervisor();
  }

  async function runContract() {
    busy(true);
    try {
      const payload = await requestJson("/api/contracts/demo/side-letter-fee", { method: "POST" });
      renderContractCompact(payload);
      if (typeof renderContractDemo === "function") renderContractDemo(payload);
      notify(`Contract control surfaced ${formatMoneyNumber(payload.analysis?.potential_overcall || 0)} potential overcall.`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      busy(false);
    }
  }

  function numericCount(text) {
    const match = String(text || "").match(/\d+/);
    return match ? Number(match[0]) : 0;
  }

  function liveExceptionCount() {
    const control = numericCount(q("#task-count")?.textContent);
    const sponsor = numericCount(q(".exception-list-head > b")?.textContent);
    return { control, sponsor, total: control + sponsor };
  }

  function syncExistingQueues() {
    const counts = liveExceptionCount();
    if (q("#navm-exception-control-count")) q("#navm-exception-control-count").textContent = counts.control;
    if (q("#navm-exception-sponsor-count")) q("#navm-exception-sponsor-count").textContent = counts.sponsor;
    if (q("#navm-live-exceptions")) q("#navm-live-exceptions").textContent = `${counts.total} surfaced`;
    if (q("#navm-review-exceptions")) q("#navm-review-exceptions").textContent = counts.total;
    if (q("#navm-stage-exception")) {
      q("#navm-stage-exception").textContent = counts.total ? `${counts.total} surfaced` : "Watching queues";
      q("#navm-stage-exception").classList.toggle("review", counts.total > 0);
    }
  }

  function syncSupervisor() {
    const existingDecision = q("#decision-badge")?.textContent.trim();
    if (runtime.reconciliation) {
      const review = runtime.reconciliation.review || {};
      q("#navm-live-reconciliation").textContent = String(review.action || "review").replaceAll("_", " ");
      q("#navm-live-reconciliation-note").textContent = review.controls_summary || `${review.controls_passed || 0} controls passed.`;
    } else if (existingDecision) {
      q("#navm-live-reconciliation").textContent = existingDecision;
      q("#navm-live-reconciliation-note").textContent = "Live control-room case; use the specialist workspace for a NAV pack review.";
    }

    if (runtime.contract) {
      q("#navm-live-contract").textContent = String(runtime.contract.analysis?.decision || "review").replaceAll("_", " ");
      q("#navm-live-contract-note").textContent = "Synthetic side-letter control executed with explicit provenance.";
    } else if (q("#contract-results") && !q("#contract-results").classList.contains("hidden")) {
      q("#navm-live-contract").textContent = q("#contract-decision-title")?.textContent || "Reviewed";
    }

    if (runtime.statement) {
      q("#navm-live-statement").textContent = "Evidence surfaced";
      const diff = runtime.statement.period_diff;
      q("#navm-live-statement-note").textContent = diff ? `${diff.lines_added?.length || 0} added · ${diff.lines_removed?.length || 0} removed.` : "Current statement read with deterministic text tools.";
    }

    syncExistingQueues();
    renderReviewPanel();
  }

  function reviewRows() {
    const rows = [];
    if (runtime.statement) {
      const sources = runtime.statement.evidence?.sources?.length || 1;
      rows.push(["Statement Agent", "Evidence surfaced", `${sources} source${sources === 1 ? "" : "s"} hashed`]);
    } else rows.push(["Statement Agent", "Not run in supervisor workspace", "Ready"]);
    if (runtime.contract) {
      rows.push(["Contract Agent", String(runtime.contract.analysis?.decision || "review").replaceAll("_", " "), "Synthetic / context-derived"]);
    } else rows.push(["Contract Agent", "Not run in supervisor workspace", "Ready"]);
    if (runtime.reconciliation) {
      const review = runtime.reconciliation.review || {};
      rows.push(["Reconciliation Agent", String(review.action || "review").replaceAll("_", " "), `${review.controls_passed || 0} controls passed`]);
    } else rows.push(["Reconciliation Agent", "Not run in supervisor workspace", "Ready"]);
    const counts = liveExceptionCount();
    rows.push(["Exception queues", counts.total ? `${counts.total} surfaced` : "No live queue items", "Dependency tools planned"]);
    return rows;
  }

  function renderReviewPanel() {
    if (!q("#navm-review-log")) return;
    const touched = [runtime.statement, runtime.contract, runtime.reconciliation].filter(Boolean).length;
    q("#navm-review-agents").textContent = `${touched} / 3`;
    q("#navm-review-controls").textContent = runtime.reconciliation?.review?.controls_passed ?? "—";
    q("#navm-review-human").textContent = runtime.humanPrepared ? "Awaiting review" : "Required";
    q("#navm-review-log").innerHTML = reviewRows().map(([agent, status, note]) => `<div class="navm-review-log-row"><span>${esc(agent)}</span><strong>${esc(status)}</strong><small>${esc(note)}</small></div>`).join("");
    const policy = currentPolicy();
    const reconAction = runtime.reconciliation?.review?.action;
    const ready = touched > 0 && (!policy.stages.reconciliation || reconAction === "ready_to_submit") && liveExceptionCount().total === 0;
    const status = q("#navm-review-status");
    status.textContent = ready ? "Ready for human review" : runtime.humanPrepared ? "Awaiting human review" : "Evidence in progress";
    status.className = `navm-status-pill ${ready ? "" : "warning"}`;
    q("#navm-workflow-status").textContent = ready ? "Ready for human review" : touched ? "Review in progress" : "Ready to run";
  }

  function prepareHumanReview() {
    runtime.humanPrepared = true;
    q("#navm-gate-state").textContent = "Review pack prepared · awaiting explicit human decision";
    q("#navm-stage-human").textContent = "Awaiting human";
    q("#navm-stage-human").classList.add("review");
    renderReviewPanel();
    notify("Review pack marked ready for a human decision. No approval was inferred or recorded.");
  }

  function downloadSessionManifest() {
    const policy = currentPolicy();
    const counts = liveExceptionCount();
    const manifest = {
      workflow_type: "nav_control_manager_session_manifest",
      generated_at: new Date().toISOString(),
      template: policy,
      specialist_status: {
        statement: runtime.statement ? "evidence_surfaced" : "not_run",
        contract: runtime.contract?.analysis?.decision || "not_run",
        reconciliation: runtime.reconciliation?.review?.action || "not_run",
        exception_queue_count: counts.total,
        human_gate: runtime.humanPrepared ? "awaiting_human_review" : "required",
      },
      evidence_identifiers: {
        statement_sources: runtime.statement?.evidence?.sources || [],
        nav_case_id: runtime.reconciliation?.case_id || null,
        nav_review_sha256: runtime.reconciliation?.evidence?.review_sha256 || null,
        contract_fixture_sha256: runtime.contract?.evidence?.fixture_manifest_sha256 || null,
      },
      boundaries: [
        "No raw document content is included in this session manifest.",
        "No human approval is inferred by the supervisor UI.",
        "No payment initiation or official NAV amendment is performed by this workspace.",
      ],
    };
    const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "cherry-nav-control-manager-session-manifest.json";
    link.click();
    URL.revokeObjectURL(link.href);
    notify("Session manifest downloaded without raw document content.");
  }

  function openReports() {
    const actions = q(".dataset-report-actions");
    if (actions) {
      actions.scrollIntoView({ behavior: "smooth", block: "center" });
      notify("Sponsor PDF and Excel review-pack actions are here.");
      return;
    }
    const download = q("#download-review");
    if (download && !download.disabled) {
      q("#control-room")?.scrollIntoView({ behavior: "smooth", block: "start" });
      notify("The current governed case review download is available in the control-room header.");
      return;
    }
    notify("Run an analysis first to enable workflow-specific report downloads.", true);
  }

  function scrollTo(selector) {
    q(selector)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function bindWorkspaceEvents() {
    qa("[data-navm-tab]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.navmTab)));
    q("#navm-configure")?.addEventListener("click", () => showView("workflow"));
    q("#navm-open-upload")?.addEventListener("click", () => scrollTo("#upload"));
    q("#navm-workflow-form")?.addEventListener("submit", savePolicy);
    q("#navm-reset-template")?.addEventListener("click", resetPolicy);
    q("#navm-use-template")?.addEventListener("click", () => { savePolicy(); showView("agents"); notify("Session template active. Run the specialist stages needed for this review."); });
    q("#navm-jump-agents")?.addEventListener("click", () => showView("agents"));
    qa("#navm-workflow-form input, [data-navm-stage-toggle]").forEach((input) => input.addEventListener("change", updatePolicyUi));

    q("#navm-recon-form")?.addEventListener("submit", runReconciliation);
    q("#navm-use-contract-docs")?.addEventListener("change", (event) => {
      const rules = q("#navm-side-rules");
      if (rules) { rules.disabled = event.target.checked; if (event.target.checked) rules.value = ""; }
    });
    q("#navm-open-control-room")?.addEventListener("click", () => scrollTo("#control-room"));

    q("#navm-statement-form")?.addEventListener("submit", runStatement);
    q("#navm-open-upload-from-statement")?.addEventListener("click", () => scrollTo("#upload"));

    q("#navm-contract-demo")?.addEventListener("click", runContract);
    q("#navm-open-contracts")?.addEventListener("click", () => scrollTo("#contracts"));

    q("#navm-open-exceptions")?.addEventListener("click", () => scrollTo("#exception-manager"));
    q("#navm-open-sponsor-exceptions")?.addEventListener("click", () => {
      const sponsor = q(".dataset-exceptions");
      scrollTo(sponsor ? ".dataset-exceptions" : "#upload");
      if (!sponsor) notify("Run the sponsor evidence analysis to populate its exception queue.");
    });

    q("#navm-prepare-review")?.addEventListener("click", prepareHumanReview);
    q("#navm-download-manifest")?.addEventListener("click", downloadSessionManifest);
    q("#navm-open-reports")?.addEventListener("click", openReports);
  }

  function watchExistingUi() {
    const targets = [q("#decision-badge"), q("#task-count"), q("#contract-results"), q("#dataset-results")].filter(Boolean);
    targets.forEach((target) => {
      const observer = new MutationObserver(() => syncSupervisor());
      observer.observe(target, { childList: true, subtree: true, attributes: true, characterData: true });
    });
  }

  function initialiseNavManager() {
    injectStyles();
    mountWorkspace();
    wirePrimaryNav();
    bindWorkspaceEvents();
    loadPolicy();
    syncSupervisor();
    watchExistingUi();
  }

  document.addEventListener("DOMContentLoaded", initialiseNavManager);
})();
