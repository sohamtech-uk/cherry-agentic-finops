(() => {
  'use strict';

  const stage = document.getElementById('board-stage');
  const board = document.getElementById('board-inner');
  const nodesLayer = document.getElementById('nodes');
  const svg = document.getElementById('connections');
  const emptyState = document.getElementById('empty-state');
  const planPanel = document.getElementById('plan-panel');
  const planTitle = document.getElementById('plan-title');
  const planIntro = document.getElementById('plan-intro');
  const planSteps = document.getElementById('plan-steps');
  const confirmPlan = document.getElementById('confirm-plan');
  const closePlan = document.getElementById('close-plan');
  const inspector = document.getElementById('inspector');
  const closeInspector = document.getElementById('close-inspector');
  const composer = document.getElementById('composer');
  const composerInput = document.getElementById('composer-input');
  const toast = document.getElementById('toast');
  const environmentPill = document.getElementById('environment-pill');
  const scenarioActions = document.getElementById('scenario-actions');
  const scenarioStatus = document.getElementById('scenario-status');
  const investigateButton = document.getElementById('investigate-case');
  const openReview = document.getElementById('open-review');
  const zoomLabel = document.getElementById('zoom-label');

  const inspectorKind = document.getElementById('inspector-kind');
  const inspectorTitle = document.getElementById('inspector-title');
  const inspectorSummary = document.getElementById('inspector-summary');
  const inspectorDetails = document.getElementById('inspector-details');
  const inspectorSources = document.getElementById('inspector-sources');
  const inspectorRaw = document.getElementById('inspector-raw');

  let pendingScenario = null;
  let currentScenario = null;
  let currentCaseId = null;
  let zoom = 1;
  let edgeDefs = [];
  const nodeDefs = new Map();

  const plans = {
    clean: {
      title: 'Apply the £12.4k Northstar receipt',
      intro: 'A straight-through case should complete without controller intervention when evidence and arithmetic agree.',
      steps: [
        'Read the booked bank receipt and exact source identity.',
        'Link remittance lines to the two open AR invoices.',
        'Run deterministic amount, currency and invoice-state controls.',
        'Apply cash in the simulated ledger and preserve the audit evidence.'
      ]
    },
    shortpay: {
      title: 'Investigate the £500 short-pay',
      intro: 'The receipt can be matched, but the residual exceeds the approved automatic policy and must become a decision-ready exception.',
      steps: [
        'Read the booked receipt, remittance and open invoice snapshot.',
        'Match Northstar and INV-2208 using evidence, not name similarity alone.',
        'Run deterministic ledger invariants and retrieve SHORTPAY-01 v3.',
        'Hold the £9.5k cash because the £500 deduction exceeds the £50 auto limit.',
        'Assemble the policy, evidence and remaining AR state for controller review.'
      ]
    }
  };

  const moneyFormatter = new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency: 'GBP',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  });

  function money(value) {
    const number = Number(value ?? 0);
    return Number.isFinite(number) ? moneyFormatter.format(number) : '—';
  }

  function esc(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { 'Accept': 'application/json', ...(options.headers || {}) }
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* no-op */ }
    if (!response.ok) {
      const detail = payload?.detail?.message || payload?.detail || payload?.message || `${response.status} ${response.statusText}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  function notify(message, isError = false) {
    toast.textContent = message;
    toast.classList.toggle('error', isError);
    toast.classList.add('show');
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => toast.classList.remove('show'), 2800);
  }

  function setEnvironmentReady(text = 'Runtime ready') {
    environmentPill.classList.add('ready');
    environmentPill.querySelector('span').textContent = text;
  }

  async function checkRuntime() {
    try {
      const config = await fetchJSON('/api/config');
      const model = config?.gemini_model ? ` · ${config.gemini_model}` : '';
      setEnvironmentReady(`Ready${model}`);
    } catch (_) {
      environmentPill.querySelector('span').textContent = 'Demo runtime';
    }
  }

  function resetBoard() {
    nodeDefs.clear();
    edgeDefs = [];
    nodesLayer.innerHTML = '';
    svg.innerHTML = '';
    emptyState.classList.remove('hidden');
    inspector.classList.add('hidden');
    scenarioActions.classList.add('hidden');
    investigateButton.classList.add('hidden');
    openReview.classList.add('hidden');
    currentScenario = null;
    currentCaseId = null;
    stage.scrollTo({ left: 0, top: 0, behavior: 'smooth' });
  }

  function showPlan(scenario) {
    const plan = plans[scenario];
    if (!plan) return;
    pendingScenario = scenario;
    planTitle.textContent = plan.title;
    planIntro.textContent = plan.intro;
    planSteps.innerHTML = plan.steps.map((step, index) => `<li data-step="${index + 1}">${esc(step)}</li>`).join('');
    planPanel.classList.remove('hidden');
  }

  function hidePlan() {
    planPanel.classList.add('hidden');
    pendingScenario = null;
  }

  function statusClass(status = '') {
    const value = String(status).toUpperCase();
    if (value.includes('PASS') || value.includes('POSTED') || value.includes('APPLIED') || value.includes('READY')) return 'good';
    if (value.includes('REVIEW') || value.includes('HELD') || value.includes('EVIDENCE')) return 'warn';
    if (value.includes('BLOCK') || value.includes('REJECT') || value.includes('EXCEEDED')) return 'bad';
    return 'info';
  }

  function makeNode(def) {
    const el = document.createElement('article');
    el.className = `finance-node ${def.tone || ''}`.trim();
    el.dataset.nodeId = def.id;
    el.style.left = `${def.x}px`;
    el.style.top = `${def.y}px`;
    el.innerHTML = `
      <div class="node-top">
        <span class="node-kicker">${esc(def.kicker)}</span>
        <span class="node-source">${esc(def.sourceLabel || 'finance state')}</span>
      </div>
      <h3>${esc(def.title)}</h3>
      <div class="node-subtitle">${esc(def.subtitle || '')}</div>
      ${def.metric ? `<div class="node-metric"><strong>${esc(def.metric)}</strong><span>${esc(def.metricLabel || '')}</span></div>` : ''}
      <div class="node-foot">
        <span class="node-status ${statusClass(def.status)}">${esc(def.status || 'Ready')}</span>
        <span class="node-count">${esc(def.foot || 'Open details')}</span>
      </div>`;

    enableDrag(el);
    el.addEventListener('click', () => {
      if (el.dataset.dragged === '1') {
        el.dataset.dragged = '0';
        return;
      }
      selectNode(def.id);
    });
    nodesLayer.appendChild(el);
    requestAnimationFrame(() => el.classList.add('landed'));
    return el;
  }

  function enableDrag(el) {
    let startX = 0;
    let startY = 0;
    let startLeft = 0;
    let startTop = 0;
    let moved = false;

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
      const dx = (event.clientX - startX) / zoom;
      const dy = (event.clientY - startY) / zoom;
      if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
      if (!moved) return;
      const left = Math.max(12, Math.min(1215, startLeft + dx));
      const top = Math.max(12, Math.min(700, startTop + dy));
      el.style.left = `${left}px`;
      el.style.top = `${top}px`;
      const def = nodeDefs.get(el.dataset.nodeId);
      if (def) { def.x = left; def.y = top; }
      updateConnections();
    });

    el.addEventListener('pointerup', (event) => {
      if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId);
      if (moved) el.dataset.dragged = '1';
    });
  }

  function addNode(def) {
    nodeDefs.set(def.id, def);
    return makeNode(def);
  }

  function edgePath(from, to) {
    const fromEl = nodesLayer.querySelector(`[data-node-id="${from}"]`);
    const toEl = nodesLayer.querySelector(`[data-node-id="${to}"]`);
    if (!fromEl || !toEl) return null;
    const x1 = fromEl.offsetLeft + fromEl.offsetWidth;
    const y1 = fromEl.offsetTop + fromEl.offsetHeight / 2;
    const x2 = toEl.offsetLeft;
    const y2 = toEl.offsetTop + toEl.offsetHeight / 2;
    const bend = Math.max(60, Math.abs(x2 - x1) * .44);
    return { d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`, x1, y1, x2, y2 };
  }

  function updateConnections() {
    svg.innerHTML = '';
    for (const edge of edgeDefs) {
      const pathData = edgePath(edge.from, edge.to);
      if (!pathData) continue;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', pathData.d);
      if (edge.tone) path.setAttribute('class', edge.tone);
      svg.appendChild(path);
      for (const [cx, cy] of [[pathData.x1, pathData.y1], [pathData.x2, pathData.y2]]) {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', cx);
        circle.setAttribute('cy', cy);
        circle.setAttribute('r', '3');
        svg.appendChild(circle);
      }
    }
  }

  async function landBoard(defs, edges) {
    emptyState.classList.add('hidden');
    nodeDefs.clear();
    edgeDefs = [];
    nodesLayer.innerHTML = '';
    svg.innerHTML = '';
    inspector.classList.add('hidden');

    for (const def of defs) {
      addNode(def);
      await new Promise(resolve => window.setTimeout(resolve, 230));
    }
    edgeDefs = edges;
    updateConnections();
    window.setTimeout(updateConnections, 350);
  }

  function detailRows(details = []) {
    return details.map(item => `<div class="detail-row"><span>${esc(item.label)}</span><b>${esc(item.value)}</b></div>`).join('');
  }

  function sourceRows(sources = []) {
    if (!sources.length) return '<div class="source-item"><b>Derived state</b><small>No external source locator on this component.</small></div>';
    return sources.map(source => `
      <div class="source-item">
        <b>${esc(source.label || source.id || 'Evidence')}</b>
        <small>${esc(source.detail || source.locator || source.hash || '')}</small>
      </div>`).join('');
  }

  function selectNode(id) {
    const def = nodeDefs.get(id);
    if (!def) return;
    document.querySelectorAll('.finance-node').forEach(node => node.classList.toggle('selected', node.dataset.nodeId === id));
    inspectorKind.textContent = def.kicker || 'Component';
    inspectorTitle.textContent = def.title;
    inspectorSummary.textContent = def.summary || def.subtitle || 'Finance component';
    inspectorDetails.innerHTML = detailRows(def.details || []);
    inspectorSources.innerHTML = sourceRows(def.sources || []);
    inspectorRaw.textContent = JSON.stringify(def.raw || {}, null, 2);
    inspector.classList.remove('hidden');
  }

  function cleanBoard(data) {
    const receipt = data.receipt_context || {};
    const remittance = data.remittance || {};
    const outcome = data.outcome || {};
    const lines = remittance.lines || [];
    const invoices = outcome.invoices || [];
    const applications = outcome.applications || [];
    const audit = outcome.audit_events || [];
    const calls = outcome.trace?.tool_calls || [];
    const applied = outcome.receipt?.applied_amount ?? receipt.amount;
    const status = outcome.application?.status || 'POSTED_SIMULATED';

    return {
      defs: [
        {
          id: 'receipt', x: 70, y: 190, kicker: '01 · Bank evidence', sourceLabel: 'SYNTHETIC_BANK',
          title: receipt.id || 'RCPT-1041', subtitle: `${receipt.payer_name || 'Northstar Retail Ltd'} · ${receipt.settlement_status || 'BOOKED'}`,
          metric: money(receipt.amount), metricLabel: 'booked receipt', status: receipt.settlement_status || 'BOOKED', foot: 'Exact source identity',
          summary: 'A booked bank receipt is the cash-side source of truth for the application.',
          details: [
            { label: 'Receipt', value: receipt.id || 'RCPT-1041' },
            { label: 'Payer', value: receipt.payer_name || 'Northstar Retail Ltd' },
            { label: 'Reference', value: receipt.reference || 'REM-1041' },
            { label: 'Amount', value: money(receipt.amount) }
          ],
          sources: [{ label: 'Bank source', detail: `${receipt.source_system || 'SYNTHETIC_BANK'} · ${receipt.source_transaction_id || 'TX-1041'}` }], raw: receipt
        },
        {
          id: 'remittance', x: 370, y: 75, kicker: '02 · Remittance', sourceLabel: 'remittance',
          title: remittance.id || 'REM-1041', subtitle: `${lines.length} evidenced allocation lines`,
          metric: `${lines.length}`, metricLabel: 'invoice references', status: 'EVIDENCE LINKED', foot: 'Click for line detail',
          summary: 'Remittance tells Cherry CFO which invoices the customer intended to settle.',
          details: lines.map((line, i) => ({ label: line.invoice_id || `Line ${i + 1}`, value: money(line.amount) })),
          sources: (remittance.evidence_refs || []).map(ref => ({ label: 'Remittance locator', detail: ref })), raw: remittance
        },
        {
          id: 'invoices', x: 370, y: 385, kicker: '03 · Open AR', sourceLabel: 'ERP snapshot',
          title: 'Northstar open invoices', subtitle: 'Open-item state before application',
          metric: `${invoices.length || lines.length}`, metricLabel: 'matched invoices', status: 'MATCHED', foot: 'Balance state',
          summary: 'The deterministic adapter applies only against supplied open invoices and preserves resulting balances.',
          details: (invoices.length ? invoices : lines).map((invoice, i) => ({
            label: invoice.invoice_id || invoice.id || `Invoice ${i + 1}`,
            value: invoice.balance_after !== undefined ? `${money(invoice.balance_after)} after` : money(invoice.amount)
          })),
          sources: [{ label: 'AR ledger', detail: 'Synthetic open-AR snapshot supplied to the control adapter' }], raw: invoices
        },
        {
          id: 'controls', x: 700, y: 220, kicker: '04 · Deterministic controls', sourceLabel: 'control engine',
          title: 'Cash application controls', subtitle: 'Amount · currency · invoice state · idempotency',
          metric: 'PASS', metricLabel: 'all required checks', status: 'PASS', foot: `${calls.length} tool calls`, tone: 'dark',
          summary: 'The model does not invent accounting figures. Deterministic code validates the application before simulated posting.',
          details: [
            { label: 'Application', value: status },
            { label: 'Applied', value: money(applied) },
            { label: 'Production write', value: outcome.production_write_performed ? 'Yes' : 'No' },
            { label: 'Tool calls', value: String(calls.length) }
          ],
          sources: calls.map(call => ({ label: call.name || 'Tool', detail: call.deterministic === false ? 'Model-assisted' : 'Deterministic finance operation' })), raw: outcome.trace || {}
        },
        {
          id: 'post', x: 1015, y: 120, kicker: '05 · Simulated ledger', sourceLabel: 'AR outcome',
          title: 'Straight-through application', subtitle: 'Receipt applied across the evidenced invoices',
          metric: money(applied), metricLabel: 'cash applied', status, foot: 'No human needed',
          summary: 'The clean case reaches a simulated posted state without unnecessary controller intervention.',
          details: [
            { label: 'Status', value: status },
            { label: 'Applications', value: String(applications.length || lines.length) },
            { label: 'Unapplied cash', value: money(outcome.receipt?.unapplied_amount || 0) }
          ],
          sources: [{ label: 'Simulation boundary', detail: data.boundary || 'No production accounting write' }], raw: outcome
        },
        {
          id: 'audit', x: 1015, y: 430, kicker: '06 · Evidence trail', sourceLabel: 'audit chain',
          title: 'Review-ready provenance', subtitle: 'Every state transition carries supplied evidence',
          metric: `${audit.length}`, metricLabel: 'audit events', status: 'READY', foot: 'Inspect provenance',
          summary: 'The board ends with verifiable state and an evidence trail rather than an ungrounded narrative answer.',
          details: [
            { label: 'Audit events', value: String(audit.length) },
            { label: 'Simulation only', value: outcome.simulation_only === false ? 'No' : 'Yes' },
            { label: 'Production write', value: outcome.production_write_performed ? 'Yes' : 'No' }
          ],
          sources: audit.map(event => ({ label: event.event_type || 'Audit event', detail: (event.evidence_refs || []).join(' · ') })), raw: audit
        }
      ],
      edges: [
        { from: 'receipt', to: 'controls', tone: 'strong' },
        { from: 'remittance', to: 'controls', tone: 'strong' },
        { from: 'invoices', to: 'controls', tone: 'strong' },
        { from: 'controls', to: 'post', tone: 'strong' },
        { from: 'controls', to: 'audit' },
        { from: 'post', to: 'audit' }
      ]
    };
  }

  function shortPayBoard(packet) {
    const receipt = packet.receipt || {};
    const match = packet.customer_invoice_match || {};
    const policy = packet.policy || {};
    const checks = packet.control_checks || [];
    const stops = packet.automation_stopped || [];
    const evidence = packet.evidence || [];
    const allowedActions = packet.allowed_actions || [];
    const audit = packet.audit_events || [];

    const byType = (type) => evidence.filter(item => item.source_type === type).map(item => ({
      label: `${item.source_type} · ${item.evidence_id}`,
      detail: `${item.locator} · ${String(item.source_sha256 || '').slice(0, 12)}…`
    }));

    return {
      defs: [
        {
          id: 'receipt', x: 55, y: 205, kicker: '01 · Bank evidence', sourceLabel: receipt.source_system || 'bank',
          title: receipt.receipt_id || 'RCPT-1042', subtitle: `${receipt.payer_name || 'Northstar Retail Ltd'} · ${receipt.settlement_status || 'BOOKED'}`,
          metric: money(receipt.amount), metricLabel: 'booked receipt', status: receipt.allocation_status || 'HELD', foot: `v${receipt.version || 1}`,
          summary: 'The cash is booked, but remains held until the material short-pay decision is valid.',
          details: [
            { label: 'Receipt', value: receipt.receipt_id || 'RCPT-1042' },
            { label: 'Transaction', value: receipt.source_transaction_id || 'TX-1042' },
            { label: 'Amount', value: money(receipt.amount) },
            { label: 'Allocation', value: receipt.allocation_status || 'HELD' }
          ], sources: byType('BANK_FEED'), raw: receipt
        },
        {
          id: 'remittance', x: 340, y: 70, kicker: '02 · Remittance', sourceLabel: 'customer evidence',
          title: 'DAMAGED_GOODS claim', subtitle: `${match.customer_name || 'Northstar Retail Ltd'} · ${match.invoice_id || 'INV-2208'}`,
          metric: money(packet.amount_at_risk), metricLabel: 'claimed deduction', status: 'EVIDENCED CLAIM', foot: 'Not independently proven',
          summary: 'The remittance supports the customer claim and invoice reference. The claim remains evidence, not an automatic accounting authority.',
          details: [
            { label: 'Customer', value: match.customer_name || 'Northstar Retail Ltd' },
            { label: 'Invoice', value: match.invoice_id || 'INV-2208' },
            { label: 'Reason', value: match.remittance_canonical_reason_code || match.remittance_raw_reason || '—' },
            { label: 'Cash proposed', value: money(match.proposed_cash_application) }
          ], sources: byType('REMITTANCE_PDF'), raw: match
        },
        {
          id: 'invoice', x: 340, y: 395, kicker: '03 · Open AR', sourceLabel: 'ERP snapshot',
          title: match.invoice_id || 'INV-2208', subtitle: `${match.customer_name || 'Northstar Retail Ltd'} · ${match.invoice_status_at_snapshot || 'OPEN'}`,
          metric: money(match.invoice_open_balance_before), metricLabel: 'open before', status: match.invoice_status_at_snapshot || 'OPEN', foot: `ledger v${match.invoice_ledger_version || 1}`,
          summary: 'The open AR snapshot is preserved until a valid controller decision determines the residual treatment.',
          details: [
            { label: 'Open before', value: money(match.invoice_open_balance_before) },
            { label: 'Cash proposed', value: money(match.proposed_cash_application) },
            { label: 'Residual', value: money(packet.amount_at_risk) },
            { label: 'Currency', value: match.invoice_currency || 'GBP' }
          ], sources: byType('AR_LEDGER'), raw: packet.remaining_ar_state || {}
        },
        {
          id: 'policy', x: 640, y: 70, kicker: '04 · Finance policy', sourceLabel: 'approved policy',
          title: `${policy.policy_id || 'SHORTPAY-01'} v${policy.version || 3}`, subtitle: 'Effective, versioned automation boundary',
          metric: money(policy.max_auto_writeoff_gbp), metricLabel: 'max auto write-off', status: policy.status || 'APPROVED', foot: `${(policy.clauses || []).length} clauses`,
          summary: 'Policy is an explicit control surface. Historical approvals cannot silently become a new automatic rule.',
          details: [
            { label: 'Policy', value: `${policy.policy_id || 'SHORTPAY-01'} v${policy.version || 3}` },
            { label: 'Effective', value: policy.effective_from || '—' },
            { label: 'Auto limit', value: money(policy.max_auto_writeoff_gbp) },
            { label: 'Auto reasons', value: (policy.allowed_auto_reason_codes || []).join(', ') || '—' }
          ], sources: byType('POLICY'), raw: policy
        },
        {
          id: 'controls', x: 640, y: 395, kicker: '05 · Deterministic controls', sourceLabel: 'control engine',
          title: 'Accounting invariants', subtitle: 'Receipt identity · versions · currency · allocation · balance',
          metric: `${checks.filter(check => check.outcome === 'PASS').length}/${checks.length || 0}`, metricLabel: 'fundamental checks pass', status: checks.some(check => check.outcome === 'BLOCK') ? 'BLOCK' : 'PASS', foot: 'Cannot be bypassed', tone: 'dark',
          summary: 'Fundamental ledger invariants are authoritative and cannot be overridden by a model or an approval button.',
          details: checks.map(check => ({ label: check.code, value: check.outcome })),
          sources: checks.map(check => ({ label: check.code, detail: check.explanation })), raw: checks
        },
        {
          id: 'exception', x: 935, y: 220, kicker: '06 · Exception', sourceLabel: 'policy + evidence',
          title: 'Material short-pay', subtitle: stops[0]?.explanation || 'Automatic treatment is not permitted',
          metric: money(packet.amount_at_risk), metricLabel: 'amount at risk', status: packet.exception_status || 'WAITING_REVIEW', foot: `${stops.length} stop reasons`, tone: 'alert',
          summary: 'Cherry CFO has done the investigation. The remaining step is a finance judgement, not more data gathering.',
          details: [
            { label: 'Disposition', value: packet.control_disposition || 'REVIEW_REQUIRED' },
            { label: 'Application', value: packet.application_status || 'REVIEW_REQUIRED' },
            { label: 'Amount at risk', value: money(packet.amount_at_risk) },
            ...stops.map(stop => ({ label: stop.code, value: money(stop.excess_over_auto_limit) + ' over limit' }))
          ],
          sources: evidence.map(item => ({ label: `${item.source_type} · ${item.evidence_id}`, detail: item.supports })), raw: { stops, evidence }
        },
        {
          id: 'review', x: 1190, y: 220, kicker: '07 · Human judgement', sourceLabel: 'controller packet',
          title: 'Decision-ready review', subtitle: 'Evidence, policy, financial impact and allowed actions',
          metric: `${allowedActions.length}`, metricLabel: 'governed actions', status: packet.review_status || 'AWAITING_CONTROLLER', foot: 'Open controller review',
          summary: 'The controller receives a compact accounting decision packet instead of a vague confidence score.',
          details: allowedActions.map(action => ({ label: action.label, value: action.authority_required ? 'Authority required' : 'Available' })),
          sources: evidence.map(item => ({ label: item.evidence_id, detail: item.locator })), raw: packet
        },
        {
          id: 'audit', x: 935, y: 550, kicker: '08 · Audit trail', sourceLabel: 'hash chain',
          title: 'Evidence-linked state', subtitle: 'Every review transition is reproducible',
          metric: `${audit.length}`, metricLabel: 'audit events', status: 'READY', foot: 'No production write',
          summary: 'The workflow preserves evidence identities, policy versions and review state without mutating production accounting systems.',
          details: [
            { label: 'Events', value: String(audit.length) },
            { label: 'Simulation only', value: packet.simulation_only ? 'Yes' : 'No' },
            { label: 'Production write', value: packet.production_write_performed ? 'Yes' : 'No' },
            { label: 'Review version', value: String(packet.review_version || 1) }
          ],
          sources: audit.map(event => ({ label: `${event.sequence}. ${event.action}`, detail: String(event.event_hash || '').slice(0, 16) + '…' })), raw: audit
        }
      ],
      edges: [
        { from: 'receipt', to: 'controls', tone: 'strong' },
        { from: 'remittance', to: 'exception', tone: 'alert' },
        { from: 'invoice', to: 'controls', tone: 'strong' },
        { from: 'policy', to: 'exception', tone: 'alert' },
        { from: 'controls', to: 'exception', tone: 'alert' },
        { from: 'exception', to: 'review', tone: 'alert' },
        { from: 'exception', to: 'audit' },
        { from: 'review', to: 'audit' }
      ]
    };
  }

  async function runScenario(scenario) {
    currentScenario = scenario;
    currentCaseId = null;
    scenarioActions.classList.remove('hidden');
    investigateButton.classList.add('hidden');
    openReview.classList.add('hidden');
    scenarioStatus.textContent = 'Running controls…';

    if (scenario === 'clean') {
      const data = await fetchJSON('/api/controller-review/demo/clean-multi-invoice', { method: 'POST' });
      const boardData = cleanBoard(data);
      await landBoard(boardData.defs, boardData.edges);
      scenarioStatus.textContent = 'Straight-through application complete';
      notify('Clean cash application completed with deterministic controls.');
      return;
    }

    const packet = await fetchJSON('/api/controller-review/demo/short-pay-500/reset', { method: 'POST' });
    currentCaseId = packet.case_id;
    const boardData = shortPayBoard(packet);
    await landBoard(boardData.defs, boardData.edges);
    scenarioStatus.textContent = `${packet.case_id} · controller judgement required`;
    investigateButton.classList.remove('hidden');
    openReview.classList.remove('hidden');
    notify('£500 short-pay held and routed to controller review.');
  }

  async function confirmPendingPlan() {
    if (!pendingScenario) return;
    const scenario = pendingScenario;
    confirmPlan.disabled = true;
    confirmPlan.innerHTML = 'Running finance controls…';
    try {
      planPanel.classList.add('hidden');
      await runScenario(scenario);
      pendingScenario = null;
    } catch (error) {
      notify(error.message || 'Unable to run case.', true);
      planPanel.classList.remove('hidden');
    } finally {
      confirmPlan.disabled = false;
      confirmPlan.innerHTML = 'Confirm &amp; run <span>→</span>';
    }
  }

  async function investigateCurrentCase() {
    if (!currentCaseId) return;
    investigateButton.disabled = true;
    investigateButton.textContent = 'Investigating…';
    try {
      const result = await fetchJSON(`/api/controller-review/cases/${encodeURIComponent(currentCaseId)}/agent-investigation`, { method: 'POST' });
      const node = {
        id: 'investigation', x: 1190, y: 540, kicker: '09 · Agent investigation', sourceLabel: 'read-only agent',
        title: 'Exception investigation', subtitle: result.summary || result.narrative || result.recommended_action || 'Evidence-grounded investigation completed',
        metric: 'READ', metricLabel: 'no ledger authority', status: 'ADVISORY', foot: 'Inspect agent output',
        summary: 'The agent can investigate and explain context, but it cannot override deterministic finance controls or record the controller decision.',
        details: Object.entries(result).slice(0, 7).map(([key, value]) => ({ label: key, value: typeof value === 'object' ? JSON.stringify(value) : String(value) })),
        sources: [{ label: 'Controller packet', detail: currentCaseId }, { label: 'Authority boundary', detail: 'Read-only investigation; no decision mutation.' }], raw: result
      };
      addNode(node);
      edgeDefs.push({ from: 'exception', to: 'investigation' });
      window.setTimeout(updateConnections, 180);
      selectNode('investigation');
      notify('Agent investigation added to the board.');
    } catch (error) {
      notify(`Agent investigation unavailable: ${error.message}`, true);
    } finally {
      investigateButton.disabled = false;
      investigateButton.textContent = 'Investigate with agent';
    }
  }

  function inferScenario(query) {
    const text = query.toLowerCase();
    if (/500|short.?pay|damaged|deduction|exception|review|held/.test(text)) return 'shortpay';
    return 'clean';
  }

  function setZoom(next) {
    zoom = Math.max(.65, Math.min(1.35, next));
    board.style.transform = `scale(${zoom})`;
    zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
  }

  document.querySelectorAll('[data-scenario]').forEach(button => {
    button.addEventListener('click', () => showPlan(button.dataset.scenario));
  });

  document.querySelectorAll('[data-action="reset-board"]').forEach(button => {
    button.addEventListener('click', resetBoard);
  });

  confirmPlan.addEventListener('click', confirmPendingPlan);
  closePlan.addEventListener('click', hidePlan);
  closeInspector.addEventListener('click', () => {
    inspector.classList.add('hidden');
    document.querySelectorAll('.finance-node').forEach(node => node.classList.remove('selected'));
  });
  investigateButton.addEventListener('click', investigateCurrentCase);

  composer.addEventListener('submit', (event) => {
    event.preventDefault();
    const query = composerInput.value.trim();
    if (!query) return;
    showPlan(inferScenario(query));
    composerInput.value = '';
  });

  document.getElementById('zoom-in').addEventListener('click', () => setZoom(zoom + .1));
  document.getElementById('zoom-out').addEventListener('click', () => setZoom(zoom - .1));
  document.getElementById('zoom-reset').addEventListener('click', () => {
    setZoom(1);
    stage.scrollTo({ left: 0, top: 0, behavior: 'smooth' });
  });

  window.addEventListener('resize', updateConnections);
  checkRuntime();
  resetBoard();
})();
