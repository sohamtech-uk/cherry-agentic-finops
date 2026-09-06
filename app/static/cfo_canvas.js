(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = {
    case: null,
    selectedFiles: [],
    zoom: 1,
    nodes: new Map(),
    edges: [],
    view: 'canvas',
    busy: false,
  };

  const dom = {
    runtime: $('runtime-pill'),
    caseCrumb: $('case-crumb'),
    boardStage: $('board-stage'),
    board: $('board-inner'),
    nodes: $('nodes'),
    connections: $('connections'),
    empty: $('empty-state'),
    inspector: $('inspector'),
    inspectorKind: $('inspector-kind'),
    inspectorTitle: $('inspector-title'),
    inspectorSummary: $('inspector-summary'),
    inspectorDetails: $('inspector-details'),
    inspectorSources: $('inspector-sources'),
    inspectorRaw: $('inspector-raw'),
    closeInspector: $('close-inspector'),
    documentList: $('document-list'),
    dockItems: $('dock-items'),
    dropOverlay: $('drop-overlay'),
    fileInput: $('file-input'),
    uploadDialog: $('upload-dialog'),
    selectedFiles: $('selected-files'),
    chooseFiles: $('choose-files'),
    uploadSubmit: $('upload-submit'),
    fundName: $('fund-name'),
    reportingPeriod: $('reporting-period'),
    asOfDate: $('as-of-date'),
    readiness: $('run-readiness'),
    reconcile: $('run-reconcile'),
    review: $('run-review'),
    decision: $('open-decision'),
    decisionDialog: $('decision-dialog'),
    decisionNote: $('decision-note'),
    stageReadiness: $('stage-readiness'),
    stageReconcile: $('stage-reconcile'),
    stageReview: $('stage-review'),
    stageDecision: $('stage-decision'),
    composer: $('composer'),
    composerInput: $('composer-input'),
    toast: $('toast'),
    zoomLabel: $('zoom-label'),
    reportDate: $('report-date'),
    reportFund: $('report-fund'),
    reportPeriod: $('report-period'),
    reportStatus: $('report-status'),
    reportSummary: $('report-summary'),
    reportEvidence: $('report-evidence'),
    reportControls: $('report-controls'),
    reportFindings: $('report-findings'),
    reportDecision: $('report-decision'),
  };

  function esc(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function pretty(value) {
    return String(value ?? '')
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function shortHash(value) {
    const text = String(value || '');
    return text ? `${text.slice(0, 8)}…${text.slice(-6)}` : '—';
  }

  function notify(message, error = false) {
    dom.toast.textContent = message;
    dom.toast.classList.toggle('error', error);
    dom.toast.classList.add('show');
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => dom.toast.classList.remove('show'), 3000);
  }

  async function api(url, options = {}) {
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    const response = await fetch(url, { ...options, headers });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* non-json */ }
    if (!response.ok) {
      const detail = payload?.detail?.message || payload?.detail || payload?.message || `${response.status} ${response.statusText}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  function setBusy(busy, label) {
    state.busy = busy;
    [dom.readiness, dom.reconcile, dom.review, dom.decision, dom.uploadSubmit].forEach((button) => {
      if (button) button.dataset.busy = busy ? '1' : '0';
    });
    if (label) notify(label);
    refreshControls();
  }

  function workflow() {
    return state.case?.workflows?.nav_quality_controller || {};
  }

  function sources() {
    return state.case?.classification?.sources || [];
  }

  function fileExt(name) {
    const bits = String(name || '').toLowerCase().split('.');
    return bits.length > 1 ? bits.pop() : 'file';
  }

  function fileLabel(source) {
    const type = source.detected_type || 'unknown';
    const labels = {
      nav_summary: 'NAV summary',
      nav_workbook: 'NAV workbook',
      investor_gl: 'Investor GL',
      side_letter_rules: 'Side-letter rules',
      financial_statement: 'Financial statement',
      investor_report: 'Investor report',
      bank_statement: 'Bank statement',
      cash_transactions: 'Cash data',
      bank_transactions: 'Bank transactions',
      positions: 'Positions',
      trades: 'Trades',
      lpa: 'LPA',
      side_letter: 'Side letter',
      capital_call_notice: 'Capital call',
    };
    return labels[type] || pretty(type);
  }

  function renderDocuments() {
    const items = sources();
    if (!items.length) {
      dom.documentList.innerHTML = '<div class="empty-docs">Upload NAV evidence to start the workbench.</div>';
      return;
    }
    dom.documentList.innerHTML = items.map((source) => {
      const ext = fileExt(source.filename);
      const rejected = source.validation_status !== 'accepted';
      return `<button class="document-item" type="button" data-node-target="source-${esc(source.id)}">
        <span class="doc-icon ${esc(ext)}">${esc(ext.slice(0, 4).toUpperCase())}</span>
        <span><b>${esc(source.filename)}</b><small>${esc(fileLabel(source))}</small></span>
        <span class="doc-status ${rejected ? 'rejected' : ''}">${rejected ? 'Review' : 'Ready'}</span>
      </button>`;
    }).join('');
    dom.documentList.querySelectorAll('[data-node-target]').forEach((button) => {
      button.addEventListener('click', () => selectNode(button.dataset.nodeTarget));
    });
  }

  function statusClass(status = '') {
    const value = String(status).toUpperCase();
    if (value.includes('PASS') || value.includes('READY') || value.includes('APPROVE') || value.includes('ACCEPT')) return 'good';
    if (value.includes('REVIEW') || value.includes('WARNING') || value.includes('OPTIONAL') || value.includes('RETURN')) return 'warn';
    if (value.includes('BLOCK') || value.includes('REJECT') || value.includes('FAIL') || value.includes('ESCALATE')) return 'bad';
    return 'info';
  }

  function makeNode(def) {
    const el = document.createElement('article');
    el.className = `finance-node ${def.tone || ''} ${def.wide ? 'wide' : ''}`.trim();
    el.dataset.nodeId = def.id;
    el.style.left = `${def.x}px`;
    el.style.top = `${def.y}px`;
    el.innerHTML = `
      <div class="node-top">
        <span class="node-kicker">${esc(def.kicker)}</span>
        <span class="node-source">${esc(def.sourceLabel || 'NAV state')}</span>
      </div>
      <h3>${esc(def.title)}</h3>
      <div class="node-subtitle">${esc(def.subtitle || '')}</div>
      ${def.metric ? `<div class="node-metric"><strong>${esc(def.metric)}</strong><span>${esc(def.metricLabel || '')}</span></div>` : ''}
      <div class="node-foot">
        <span class="node-status ${statusClass(def.status)}">${esc(def.status || 'Ready')}</span>
        <span>${esc(def.foot || 'Open details')}</span>
      </div>`;
    enableDrag(el);
    el.addEventListener('click', () => {
      if (el.dataset.dragged === '1') {
        el.dataset.dragged = '0';
        return;
      }
      selectNode(def.id);
    });
    dom.nodes.appendChild(el);
    requestAnimationFrame(() => el.classList.add('landed'));
  }

  function addNode(def) {
    state.nodes.set(def.id, def);
    makeNode(def);
  }

  function enableDrag(el) {
    let startX = 0, startY = 0, startLeft = 0, startTop = 0, moved = false;
    el.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      startX = event.clientX;
      startY = event.clientY;
      startLeft = parseFloat(el.style.left) || 0;
      startTop = parseFloat(el.style.top) || 0;
      moved = false;
      el.setPointerCapture(event.pointerId);
    });
    el.addEventListener('pointermove', (event) => {
      if (!el.hasPointerCapture(event.pointerId)) return;
      const dx = (event.clientX - startX) / state.zoom;
      const dy = (event.clientY - startY) / state.zoom;
      if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
      if (!moved) return;
      const left = Math.max(12, Math.min(1480, startLeft + dx));
      const top = Math.max(12, Math.min(900, startTop + dy));
      el.style.left = `${left}px`;
      el.style.top = `${top}px`;
      const def = state.nodes.get(el.dataset.nodeId);
      if (def) { def.x = left; def.y = top; }
      updateConnections();
    });
    el.addEventListener('pointerup', (event) => {
      if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId);
      if (moved) el.dataset.dragged = '1';
    });
  }

  function edgePath(from, to) {
    const a = dom.nodes.querySelector(`[data-node-id="${CSS.escape(from)}"]`);
    const b = dom.nodes.querySelector(`[data-node-id="${CSS.escape(to)}"]`);
    if (!a || !b) return null;
    const x1 = a.offsetLeft + a.offsetWidth;
    const y1 = a.offsetTop + a.offsetHeight / 2;
    const x2 = b.offsetLeft;
    const y2 = b.offsetTop + b.offsetHeight / 2;
    const bend = Math.max(55, Math.abs(x2 - x1) * .42);
    return { d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`, x1, y1, x2, y2 };
  }

  function updateConnections() {
    dom.connections.innerHTML = '';
    state.edges.forEach((edge) => {
      const data = edgePath(edge.from, edge.to);
      if (!data) return;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', data.d);
      if (edge.tone) path.setAttribute('class', edge.tone);
      dom.connections.appendChild(path);
      [[data.x1, data.y1], [data.x2, data.y2]].forEach(([cx, cy]) => {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', cx); circle.setAttribute('cy', cy); circle.setAttribute('r', '3');
        dom.connections.appendChild(circle);
      });
    });
  }

  function sourceDetails(source) {
    const warnings = source.validation_errors || source.warnings || [];
    return [
      { label: 'Detected type', value: fileLabel(source) },
      { label: 'Validation', value: pretty(source.validation_status || source.status) },
      { label: 'Source ID', value: source.id || '—' },
      { label: 'SHA-256', value: shortHash(source.sha256) },
      ...(warnings.length ? [{ label: 'Warnings', value: `${warnings.length}` }] : []),
    ];
  }

  function sourceLineage(source) {
    const warnings = source.validation_errors || source.warnings || [];
    const items = [{ label: 'Uploaded evidence', detail: `${source.filename} · ${shortHash(source.sha256)}` }];
    warnings.forEach((warning) => items.push({ label: 'Validation note', detail: warning }));
    return items;
  }

  function buildBoard() {
    state.nodes.clear();
    state.edges = [];
    dom.nodes.innerHTML = '';
    dom.connections.innerHTML = '';
    dom.inspector.classList.add('hidden');

    const items = sources();
    const nav = workflow();
    const readiness = nav.readiness;
    const reconciliation = nav.reconciliation;
    const review = nav.review;
    const decision = nav.decision;

    if (!items.length) {
      dom.empty.classList.remove('hidden');
      renderDock();
      return;
    }
    dom.empty.classList.add('hidden');

    const sourcePositions = items.map((_, index) => ({
      x: 70 + (index % 2) * 320,
      y: 120 + Math.floor(index / 2) * 205,
    }));

    items.forEach((source, index) => {
      const rejected = source.validation_status !== 'accepted';
      const pos = sourcePositions[index];
      addNode({
        id: `source-${source.id}`,
        x: pos.x, y: pos.y,
        kicker: `${String(index + 1).padStart(2, '0')} · Evidence`,
        sourceLabel: source.id,
        title: source.filename,
        subtitle: fileLabel(source),
        metric: rejected ? 'Review' : 'Accepted',
        metricLabel: 'classification',
        status: rejected ? 'REVIEW' : 'READY',
        tone: rejected ? 'alert' : '',
        foot: shortHash(source.sha256),
        summary: rejected
          ? 'This source remains in the evidence manifest but is excluded from control planning until its input contract is satisfied.'
          : 'Recognised evidence passed the deterministic input contract and is available to the NAV controller.',
        details: sourceDetails(source),
        sources: sourceLineage(source),
        raw: source,
      });
    });

    if (readiness) {
      const controls = readiness.controls || [];
      const readyCount = controls.filter((item) => item.status === 'ready').length;
      addNode({
        id: 'nav-readiness', x: 760, y: 190, wide: true,
        kicker: 'NAV controller · Readiness', sourceLabel: readiness.mode || 'waiting',
        title: 'Evidence readiness', subtitle: readiness.status === 'ready'
          ? 'Supported checks are enabled from the evidence supplied.'
          : 'More NAV evidence is needed before controls can run.',
        metric: `${readyCount}/${controls.length}`, metricLabel: 'controls ready',
        status: readiness.status === 'ready' ? 'READY' : 'NEEDS INPUT',
        tone: readiness.status === 'ready' ? 'dark' : 'alert',
        foot: `${(readiness.optional_gaps || []).length} optional gaps`,
        summary: readiness.control_boundary,
        details: [
          { label: 'Mode', value: pretty(readiness.mode) },
          { label: 'Controls ready', value: `${readyCount} of ${controls.length}` },
          { label: 'Optional gaps', value: (readiness.optional_gaps || []).join(', ') || 'None' },
          { label: 'Blockers', value: `${(readiness.blockers || []).length}` },
        ],
        sources: Object.entries(readiness.inputs || {}).filter(([, value]) => value).map(([key, value]) => ({
          label: pretty(key), detail: `${value.filename || value.source_id || ''}`,
        })),
        raw: readiness,
      });
      items.filter((source) => source.validation_status === 'accepted').forEach((source) => {
        state.edges.push({ from: `source-${source.id}`, to: 'nav-readiness', tone: 'strong' });
      });
    }

    if (reconciliation) {
      const recReview = reconciliation.review || {};
      const findings = recReview.findings || [];
      const exceptions = Number(recReview.exceptions_open ?? findings.filter((f) => f.severity !== 'pass').length);
      addNode({
        id: 'nav-reconciliation', x: 1110, y: 190, wide: true,
        kicker: 'NAV controller · Deterministic', sourceLabel: 'control result',
        title: reconciliation.partial ? 'Partial NAV reconciliation' : 'NAV reconciliation',
        subtitle: reconciliation.legal_entity || state.case.fund_name || 'NAV control result',
        metric: `${recReview.controls_passed ?? '—'}`, metricLabel: 'controls passed',
        status: recReview.action || (exceptions ? 'NEEDS REVIEW' : 'PASS'),
        tone: exceptions ? 'alert' : 'dark',
        foot: `${exceptions} open exception${exceptions === 1 ? '' : 's'}`,
        summary: reconciliation.financial_boundary || 'Deterministic NAV controls completed from supplied evidence.',
        details: [
          { label: 'Legal entity', value: reconciliation.legal_entity || '—' },
          { label: 'Period end', value: reconciliation.period_end || '—' },
          { label: 'Controls passed', value: recReview.controls_passed ?? '—' },
          { label: 'Exceptions open', value: exceptions },
          { label: 'Round', value: reconciliation.iteration?.round_number ?? '1' },
        ],
        sources: Object.entries(reconciliation.evidence?.input_sha256 || {}).map(([key, value]) => ({
          label: pretty(key), detail: shortHash(value),
        })),
        raw: reconciliation,
      });
      if (readiness) state.edges.push({ from: 'nav-readiness', to: 'nav-reconciliation', tone: exceptions ? 'alert' : 'strong' });

      findings.filter((finding) => finding.severity !== 'pass').slice(0, 4).forEach((finding, index) => {
        const id = `finding-${index + 1}`;
        addNode({
          id, x: 1070 + (index % 2) * 320, y: 450 + Math.floor(index / 2) * 195,
          kicker: `Open item · ${finding.severity || 'warning'}`, sourceLabel: finding.code || 'nav.finding',
          title: finding.title || 'NAV exception', subtitle: finding.detail || '',
          metric: finding.amount ? String(finding.amount) : 'Open', metricLabel: finding.amount ? 'amount' : 'exception',
          status: finding.severity || 'REVIEW', tone: 'alert', foot: 'Deterministic finding',
          summary: finding.detail || 'A deterministic NAV control identified an open item.',
          details: [
            { label: 'Code', value: finding.code || '—' },
            { label: 'Severity', value: pretty(finding.severity || 'warning') },
            { label: 'Recommended action', value: pretty(recReview.action || 'needs_review') },
          ],
          sources: [{ label: 'Control result', detail: 'Generated by deterministic NAV reconciliation.' }],
          raw: finding,
        });
        state.edges.push({ from: 'nav-reconciliation', to: id, tone: 'alert' });
      });
    }

    if (review) {
      const pack = review.remediation_package || {};
      addNode({
        id: 'nav-agent-review', x: 1450, y: 190, wide: true,
        kicker: 'NAV controller · Agentic review', sourceLabel: 'read-only agent',
        title: 'Consolidated remediation', subtitle: 'Root causes, evidence gaps and administrator actions in one pass.',
        metric: String(pack.finding_count ?? (review.investigations || []).length), metricLabel: 'findings consolidated',
        status: pack.recommended_action || review.deterministic_action || 'REVIEWED',
        tone: 'dark', foot: `${pack.root_cause_count ?? 0} root causes`,
        summary: review.control_boundary || pack.purpose,
        details: [
          { label: 'Findings', value: pack.finding_count ?? '—' },
          { label: 'Root causes', value: pack.root_cause_count ?? '—' },
          { label: 'Work items', value: pack.work_item_count ?? '—' },
          { label: 'Recommended action', value: pretty(pack.recommended_action || '—') },
        ],
        sources: [{ label: 'Deterministic control result', detail: 'Agent explanation cannot change the NAV calculation or control result.' }],
        raw: review,
      });
      if (reconciliation) state.edges.push({ from: 'nav-reconciliation', to: 'nav-agent-review', tone: 'strong' });
    }

    if (decision) {
      addNode({
        id: 'nav-decision', x: 1450, y: 485, wide: true,
        kicker: 'Human judgement', sourceLabel: 'recorded decision',
        title: pretty(decision.action), subtitle: decision.note || 'Decision recorded by the fund-manager UI user.',
        metric: 'Human', metricLabel: 'decision owner',
        status: decision.action, tone: decision.action.includes('approve') ? 'dark' : 'alert',
        foot: decision.recorded_at ? new Date(decision.recorded_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Recorded',
        summary: decision.financial_boundary,
        details: [
          { label: 'Action', value: pretty(decision.action) },
          { label: 'Actor', value: decision.actor || 'fund-manager-ui-user' },
          { label: 'Recorded', value: decision.recorded_at ? new Date(decision.recorded_at).toLocaleString() : '—' },
        ],
        sources: [{ label: 'Review state', detail: 'Human decision is recorded after deterministic reconciliation and agentic review.' }],
        raw: decision,
      });
      if (review) state.edges.push({ from: 'nav-agent-review', to: 'nav-decision', tone: 'strong' });
    }

    updateConnections();
    setTimeout(updateConnections, 300);
    renderDock();
  }

  function detailRows(items = []) {
    return items.map((item) => `<div class="detail-row"><span>${esc(item.label)}</span><b>${esc(item.value)}</b></div>`).join('');
  }

  function sourceRows(items = []) {
    if (!items.length) return '<div class="source-item"><b>Derived state</b><small>No external locator is exposed for this component.</small></div>';
    return items.map((item) => `<div class="source-item"><b>${esc(item.label)}</b><small>${esc(item.detail)}</small></div>`).join('');
  }

  function selectNode(id) {
    const def = state.nodes.get(id);
    if (!def) return;
    document.querySelectorAll('.finance-node').forEach((node) => node.classList.toggle('selected', node.dataset.nodeId === id));
    dom.inspectorKind.textContent = def.kicker || 'Component';
    dom.inspectorTitle.textContent = def.title;
    dom.inspectorSummary.textContent = def.summary || def.subtitle || '';
    dom.inspectorDetails.innerHTML = detailRows(def.details || []);
    dom.inspectorSources.innerHTML = sourceRows(def.sources || []);
    dom.inspectorRaw.textContent = JSON.stringify(def.raw || {}, null, 2);
    dom.inspector.classList.remove('hidden');
  }

  function renderDock() {
    const items = sources();
    const generated = [];
    const nav = workflow();
    if (nav.readiness) generated.push({ id: 'nav-readiness', label: 'Readiness', mark: 'R', cls: 'generated' });
    if (nav.reconciliation) generated.push({ id: 'nav-reconciliation', label: 'Controls', mark: '✓', cls: nav.reconciliation.review?.exceptions_open ? 'alert' : 'generated' });
    if (nav.review) generated.push({ id: 'nav-agent-review', label: 'Review', mark: '✦', cls: 'generated' });
    if (nav.decision) generated.push({ id: 'nav-decision', label: 'Decision', mark: 'H', cls: nav.decision.action?.includes('approve') ? 'generated' : 'alert' });

    if (!items.length && !generated.length) {
      dom.dockItems.innerHTML = '<span class="dock-empty">Uploaded evidence and generated controls appear here.</span>';
      return;
    }
    const docs = items.map((source) => ({
      id: `source-${source.id}`,
      label: source.filename,
      mark: fileExt(source.filename).slice(0, 3).toUpperCase(),
      cls: source.validation_status === 'accepted' ? '' : 'alert',
    }));
    dom.dockItems.innerHTML = [...docs, ...generated].map((item) =>
      `<button class="dock-item ${item.cls}" type="button" data-node-target="${esc(item.id)}"><i>${esc(item.mark)}</i><span>${esc(item.label)}</span></button>`
    ).join('');
    dom.dockItems.querySelectorAll('[data-node-target]').forEach((button) => button.addEventListener('click', () => selectNode(button.dataset.nodeTarget)));
  }

  function refreshControls() {
    const nav = workflow();
    const hasCase = Boolean(state.case?.case_id);
    const readinessReady = nav.readiness?.status === 'ready';
    dom.readiness.disabled = !hasCase || state.busy;
    dom.reconcile.disabled = !readinessReady || state.busy;
    dom.review.disabled = !nav.reconciliation || state.busy;
    dom.decision.disabled = !nav.review || state.busy;

    const rows = document.querySelectorAll('.workflow-row');
    rows[0].disabled = !hasCase;
    rows[1].disabled = !readinessReady;
    rows[2].disabled = !nav.reconciliation;
    rows[3].disabled = !nav.review;

    if (!hasCase) {
      dom.stageReadiness.textContent = 'Waiting for evidence';
      dom.stageReconcile.textContent = 'Not run';
      dom.stageReview.textContent = 'Not run';
      dom.stageDecision.textContent = 'Not recorded';
      return;
    }
    const controls = nav.readiness?.controls || [];
    const readyCount = controls.filter((item) => item.status === 'ready').length;
    dom.stageReadiness.textContent = nav.readiness ? `${readyCount}/${controls.length} controls ready` : 'Evidence uploaded';
    const rec = nav.reconciliation?.review;
    dom.stageReconcile.textContent = rec ? `${rec.controls_passed ?? '—'} passed · ${rec.exceptions_open ?? 0} open` : 'Not run';
    const pack = nav.review?.remediation_package;
    dom.stageReview.textContent = nav.review ? `${pack?.finding_count ?? 0} findings consolidated` : 'Not run';
    dom.stageDecision.textContent = nav.decision ? pretty(nav.decision.action) : 'Not recorded';
  }

  function updateCase(response) {
    state.case = response;
    if (response?.case_id) {
      sessionStorage.setItem('cherryCfoNavCaseId', response.case_id);
      dom.caseCrumb.textContent = response.case_id;
    }
    renderDocuments();
    buildBoard();
    refreshControls();
    renderReport();
  }

  async function assessReadiness(silent = false) {
    if (!state.case?.case_id || state.busy) return;
    try {
      setBusy(true, silent ? null : 'Assessing NAV evidence readiness…');
      const response = await api(`/api/fund-manager/cases/${encodeURIComponent(state.case.case_id)}/nav/readiness`, { method: 'POST' });
      updateCase(response);
      if (!silent) notify(response.workflows?.nav_quality_controller?.readiness?.status === 'ready' ? 'NAV controller is ready to run supported checks.' : 'Readiness completed — additional evidence may be useful.');
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function runReconciliation() {
    if (!state.case?.case_id || state.busy) return;
    try {
      setBusy(true, 'Running deterministic NAV controls…');
      const response = await api(`/api/fund-manager/cases/${encodeURIComponent(state.case.case_id)}/nav/reconcile`, { method: 'POST' });
      updateCase(response);
      notify('NAV reconciliation complete. Deterministic findings are on the canvas.');
      selectNode('nav-reconciliation');
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function runReview() {
    if (!state.case?.case_id || state.busy) return;
    try {
      setBusy(true, 'Agent is consolidating exceptions and remediation…');
      const response = await api(`/api/fund-manager/cases/${encodeURIComponent(state.case.case_id)}/nav/review`, { method: 'POST' });
      updateCase(response);
      notify('Agentic NAV review complete. Human judgement remains required for sign-off.');
      selectNode('nav-agent-review');
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function recordDecision(action) {
    if (!state.case?.case_id || state.busy) return;
    try {
      setBusy(true, 'Recording human NAV decision…');
      const response = await api(`/api/fund-manager/cases/${encodeURIComponent(state.case.case_id)}/nav/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, note: dom.decisionNote.value.trim() || null }),
      });
      updateCase(response);
      dom.decisionDialog.close();
      notify(`Decision recorded: ${pretty(action)}.`);
      selectNode('nav-decision');
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  function openUpload() {
    state.selectedFiles = [];
    dom.selectedFiles.innerHTML = '';
    dom.uploadSubmit.disabled = true;
    if (state.case) {
      dom.fundName.value = state.case.fund_name || '';
      dom.reportingPeriod.value = state.case.reporting_period || '';
      dom.asOfDate.value = state.case.as_of_date || '';
      [dom.fundName, dom.reportingPeriod, dom.asOfDate].forEach((input) => input.disabled = true);
    } else {
      [dom.fundName, dom.reportingPeriod, dom.asOfDate].forEach((input) => input.disabled = false);
    }
    dom.uploadDialog.showModal();
  }

  function setSelectedFiles(files) {
    state.selectedFiles = Array.from(files || []).slice(0, 25);
    dom.selectedFiles.innerHTML = state.selectedFiles.map((file) =>
      `<div class="selected-file"><span>${esc(file.name)}</span><small>${(file.size / 1024 / 1024).toFixed(file.size > 1048576 ? 1 : 2)} MB</small></div>`
    ).join('');
    dom.uploadSubmit.disabled = !state.selectedFiles.length;
  }

  async function uploadSelected() {
    if (!state.selectedFiles.length || state.busy) return;
    const form = new FormData();
    state.selectedFiles.forEach((file) => form.append('files', file, file.name));
    let endpoint = '/api/fund-manager/cases';
    if (state.case?.case_id) {
      endpoint = `/api/fund-manager/cases/${encodeURIComponent(state.case.case_id)}/evidence`;
    } else {
      if (dom.fundName.value.trim()) form.append('fund_name', dom.fundName.value.trim());
      if (dom.reportingPeriod.value.trim()) form.append('reporting_period', dom.reportingPeriod.value.trim());
      if (dom.asOfDate.value) form.append('as_of_date', dom.asOfDate.value);
    }

    try {
      setBusy(true, `Uploading ${state.selectedFiles.length} evidence file${state.selectedFiles.length === 1 ? '' : 's'}…`);
      const response = await api(endpoint, { method: 'POST', body: form });
      dom.uploadDialog.close();
      updateCase(response);
      notify(`${response.classification?.accepted_count ?? 0} evidence source${response.classification?.accepted_count === 1 ? '' : 's'} accepted. Building NAV readiness…`);
      setBusy(false);
      await assessReadiness(true);
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  function renderReport() {
    dom.reportDate.textContent = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    if (!state.case) {
      dom.reportFund.textContent = 'Not supplied';
      dom.reportPeriod.textContent = 'Not supplied';
      dom.reportStatus.textContent = 'Waiting for evidence';
      dom.reportSummary.textContent = 'Upload evidence to generate a review summary.';
      dom.reportEvidence.innerHTML = '<div class="report-card"><strong>No evidence yet</strong><small>The document view updates as the NAV controller progresses.</small></div>';
      dom.reportControls.innerHTML = '';
      dom.reportFindings.innerHTML = '<div class="report-card"><strong>No open items</strong><small>Controls have not run.</small></div>';
      dom.reportDecision.textContent = 'No decision recorded.';
      return;
    }
    const nav = workflow();
    const ready = nav.readiness;
    const rec = nav.reconciliation;
    const review = nav.review;
    const decision = nav.decision;
    const src = sources();
    const recReview = rec?.review || {};
    const open = recReview.exceptions_open ?? (recReview.findings || []).filter((f) => f.severity !== 'pass').length;

    dom.reportFund.textContent = state.case.fund_name || rec?.legal_entity || 'NAV review';
    dom.reportPeriod.textContent = state.case.reporting_period || state.case.as_of_date || rec?.period_end || 'Not supplied';
    dom.reportStatus.textContent = decision ? pretty(decision.action) : review ? 'Awaiting human decision' : rec ? `${open} open items` : ready?.status === 'ready' ? 'Ready for controls' : 'Evidence review';
    dom.reportSummary.textContent = decision
      ? `The NAV controller completed its evidence-led review and a human recorded the decision "${pretty(decision.action)}". The system did not amend the official NAV.`
      : review
        ? `Deterministic NAV controls have completed and the agent consolidated ${review.remediation_package?.finding_count ?? open} findings into a remediation package. Human sign-off remains outstanding.`
        : rec
          ? `NAV controls completed with ${recReview.controls_passed ?? '—'} controls passed and ${open} open exception${open === 1 ? '' : 's'}.`
          : ready?.status === 'ready'
            ? `The evidence pack has been classified. ${ready.controls?.filter((c) => c.status === 'ready').length ?? 0} supported NAV controls are ready to run.`
            : 'The evidence pack has been classified and the NAV controller is waiting for a supported NAV summary or investor-level GL.';

    dom.reportEvidence.innerHTML = src.map((source) =>
      `<div class="report-row"><span>${esc(source.filename)}</span><b>${esc(fileLabel(source))}</b><b>${esc(pretty(source.validation_status))}</b></div>`
    ).join('') || '<div class="report-card">No evidence.</div>';

    const controls = ready?.controls || [];
    dom.reportControls.innerHTML = controls.map((control) =>
      `<div class="report-row"><span>${esc(control.control)}</span><b>${esc(pretty(control.status))}</b><b>${esc((control.requires || []).join(' + '))}</b></div>`
    ).join('') || '<div class="report-card"><strong>Not assessed</strong><small>Run evidence readiness first.</small></div>';

    const findings = (recReview.findings || []).filter((finding) => finding.severity !== 'pass');
    dom.reportFindings.innerHTML = findings.length
      ? findings.map((finding) => `<div class="report-card"><strong>${esc(finding.title || finding.code)}</strong><small>${esc(finding.detail || '')}</small></div>`).join('')
      : '<div class="report-card"><strong>No open deterministic findings</strong><small>Either controls have not run or the supplied checks passed.</small></div>';

    dom.reportDecision.innerHTML = decision
      ? `<div class="report-card"><strong>${esc(pretty(decision.action))}</strong><small>${esc(decision.note || 'No note supplied.')} · ${esc(decision.financial_boundary || '')}</small></div>`
      : '<div class="report-card"><strong>No decision recorded</strong><small>A human owns the final NAV sign-off decision.</small></div>';
  }

  function switchView(view) {
    state.view = view;
    document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === view));
    $('canvas-view').classList.toggle('hidden', view !== 'canvas');
    $('document-view').classList.toggle('hidden', view !== 'document');
    if (view === 'document') renderReport();
  }

  function resetWorkspace() {
    state.case = null;
    state.nodes.clear();
    state.edges = [];
    sessionStorage.removeItem('cherryCfoNavCaseId');
    dom.caseCrumb.textContent = 'New review';
    dom.nodes.innerHTML = '';
    dom.connections.innerHTML = '';
    dom.empty.classList.remove('hidden');
    dom.inspector.classList.add('hidden');
    dom.documentList.innerHTML = '<div class="empty-docs">Upload NAV evidence to start the workbench.</div>';
    dom.fundName.value = '';
    dom.reportingPeriod.value = '';
    dom.asOfDate.value = '';
    refreshControls();
    renderDock();
    renderReport();
    switchView('canvas');
    notify('New NAV review ready.');
  }

  function handleQuestion(text) {
    const q = String(text || '').trim().toLowerCase();
    if (!q) return;
    if (!state.case) {
      openUpload();
      notify('Upload the close pack first; Cherry will build the NAV control map from the evidence.');
      return;
    }
    if (q.includes('upload') || q.includes('add evidence') || q.includes('document')) {
      openUpload(); return;
    }
    if (q.includes('ready') || q.includes('readiness') || q.includes('what can')) {
      if (workflow().readiness) selectNode('nav-readiness'); else assessReadiness();
      return;
    }
    if (q.includes('reconcile') || q.includes('control') || q.includes('check') || q.includes('foot')) {
      if (workflow().reconciliation) selectNode('nav-reconciliation'); else runReconciliation();
      return;
    }
    if (q.includes('review') || q.includes('exception') || q.includes('root cause') || q.includes('investigate')) {
      if (workflow().review) selectNode('nav-agent-review');
      else if (workflow().reconciliation) runReview();
      else notify('Run NAV controls first so the agent has deterministic findings to investigate.');
      return;
    }
    if (q.includes('approve') || q.includes('sign off') || q.includes('decision')) {
      if (workflow().review) dom.decisionDialog.showModal();
      else notify('The agentic review must complete before a human decision is recorded.');
      return;
    }
    if (q.includes('report') || q.includes('summary')) {
      switchView('document'); return;
    }
    notify('Try: “what is ready?”, “run NAV controls”, “investigate exceptions”, or “show the report”.');
  }

  function applyZoom(next) {
    state.zoom = Math.min(1.25, Math.max(.65, Number(next.toFixed(2))));
    dom.board.style.transform = `scale(${state.zoom})`;
    dom.zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
    setTimeout(updateConnections, 50);
  }

  async function restoreCase() {
    const caseId = sessionStorage.getItem('cherryCfoNavCaseId');
    if (!caseId) return;
    try {
      const response = await api(`/api/fund-manager/cases/${encodeURIComponent(caseId)}`);
      updateCase(response);
      notify('Restored your NAV review.');
    } catch (_) {
      sessionStorage.removeItem('cherryCfoNavCaseId');
    }
  }

  async function checkRuntime() {
    try {
      const config = await api('/api/config');
      dom.runtime.classList.add('ready');
      dom.runtime.querySelector('span').textContent = config?.persistence_backend ? `Ready · ${config.persistence_backend}` : 'Runtime ready';
    } catch (_) {
      dom.runtime.querySelector('span').textContent = 'Demo runtime';
    }
  }

  document.querySelectorAll('[data-open-upload]').forEach((button) => button.addEventListener('click', openUpload));
  $('top-upload').addEventListener('click', openUpload);
  $('new-analysis').addEventListener('click', resetWorkspace);
  dom.chooseFiles.addEventListener('click', () => dom.fileInput.click());
  dom.fileInput.addEventListener('change', () => setSelectedFiles(dom.fileInput.files));
  dom.uploadSubmit.addEventListener('click', uploadSelected);
  dom.closeInspector.addEventListener('click', () => dom.inspector.classList.add('hidden'));
  dom.readiness.addEventListener('click', () => assessReadiness());
  dom.reconcile.addEventListener('click', runReconciliation);
  dom.review.addEventListener('click', runReview);
  dom.decision.addEventListener('click', () => dom.decisionDialog.showModal());
  document.querySelectorAll('[data-decision]').forEach((button) => button.addEventListener('click', () => recordDecision(button.dataset.decision)));
  document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
  $('zoom-in').addEventListener('click', () => applyZoom(state.zoom + .1));
  $('zoom-out').addEventListener('click', () => applyZoom(state.zoom - .1));
  $('zoom-reset').addEventListener('click', () => { applyZoom(1); dom.boardStage.scrollTo({ left: 0, top: 0, behavior: 'smooth' }); });

  document.querySelectorAll('.workflow-row').forEach((button) => button.addEventListener('click', () => {
    const kind = button.dataset.workflow;
    if (kind === 'readiness') workflow().readiness ? selectNode('nav-readiness') : assessReadiness();
    if (kind === 'reconciliation') workflow().reconciliation ? selectNode('nav-reconciliation') : runReconciliation();
    if (kind === 'review') workflow().review ? selectNode('nav-agent-review') : runReview();
    if (kind === 'decision') workflow().decision ? selectNode('nav-decision') : dom.decisionDialog.showModal();
  }));

  dom.composer.addEventListener('submit', (event) => {
    event.preventDefault();
    const value = dom.composerInput.value;
    dom.composerInput.value = '';
    handleQuestion(value);
  });

  let dragDepth = 0;
  dom.boardStage.addEventListener('dragenter', (event) => {
    if (!event.dataTransfer?.types?.includes('Files')) return;
    event.preventDefault();
    dragDepth += 1;
    dom.dropOverlay.classList.remove('hidden');
  });
  dom.boardStage.addEventListener('dragover', (event) => {
    if (!event.dataTransfer?.types?.includes('Files')) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  });
  dom.boardStage.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dom.dropOverlay.classList.add('hidden');
  });
  dom.boardStage.addEventListener('drop', (event) => {
    event.preventDefault();
    dragDepth = 0;
    dom.dropOverlay.classList.add('hidden');
    const files = event.dataTransfer?.files;
    if (!files?.length) return;
    openUpload();
    setSelectedFiles(files);
  });

  dom.uploadDialog.addEventListener('close', () => {
    dom.fileInput.value = '';
    state.selectedFiles = [];
    dom.selectedFiles.innerHTML = '';
  });

  window.addEventListener('resize', () => setTimeout(updateConnections, 40));

  refreshControls();
  renderDock();
  renderReport();
  checkRuntime();
  restoreCase();
})();