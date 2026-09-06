(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const fileInput = $('file-input');
  const uploadDialog = $('upload-dialog');
  const selectedFiles = $('selected-files');
  const boardStage = $('board-stage');
  const emptyState = $('empty-state');
  const uploadSubmit = $('upload-submit');
  const fundName = $('fund-name');
  const reportingPeriod = $('reporting-period');
  const asOfDate = $('as-of-date');
  const toast = $('toast');

  if (!fileInput || !uploadDialog || !selectedFiles || !boardStage || !emptyState || !uploadSubmit) return;

  const SAFE_REQUEST_BYTES = 3_250_000;
  const XLSX_REPACK_TRIGGER = 900_000;
  const INVESTOR_GL_SHEET = 'Investor-Level GL';
  const GL_KEEP_COLUMNS = [1, 2, 3, 21, 22, 23, 30, 31, 35];

  let staged = [];
  let internalDispatch = false;
  let layoutFrame = null;
  let activeUpload = null;
  let uploadCancelled = false;

  const folderInput = document.createElement('input');
  folderInput.type = 'file';
  folderInput.multiple = true;
  folderInput.setAttribute('webkitdirectory', '');
  folderInput.setAttribute('directory', '');
  folderInput.style.position = 'fixed';
  folderInput.style.left = '-9999px';
  folderInput.style.opacity = '0';
  document.body.appendChild(folderInput);

  function keyFor(file) {
    return `${file.name}::${file.size}::${file.lastModified || 0}`;
  }

  function dedupe(files) {
    const map = new Map();
    files.forEach((file) => map.set(keyFor(file), file));
    return Array.from(map.values()).slice(0, 25);
  }

  function setInputFiles(files) {
    const transfer = new DataTransfer();
    files.forEach((file) => transfer.items.add(file));
    fileInput.files = transfer.files;
  }

  function dispatchCombined(files) {
    staged = dedupe(files);
    setInputFiles(staged);
    internalDispatch = true;
    fileInput.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function formatMb(bytes) {
    return `${(bytes / 1024 / 1024).toFixed(bytes > 1024 * 1024 ? 1 : 2)} MB`;
  }

  function selectedTypeSummary() {
    const types = new Set(staged.map((file) => {
      const ext = file.name.includes('.') ? file.name.split('.').pop().toUpperCase() : 'FILE';
      if (['XLSX', 'XLS'].includes(ext)) return 'Excel';
      if (ext === 'PDF') return 'PDF';
      if (ext === 'CSV') return 'CSV';
      if (ext === 'JSON') return 'JSON';
      if (['TXT', 'MD'].includes(ext)) return 'Text';
      if (ext === 'ZIP') return 'ZIP';
      return ext;
    }));
    return Array.from(types).join(' · ') || 'No files selected';
  }

  function ensureMultiSourceTools() {
    let tools = uploadDialog.querySelector('.multi-source-tools');
    if (!tools) {
      tools = document.createElement('div');
      tools.className = 'multi-source-tools';
      tools.innerHTML = `
        <strong>Mix evidence from different sources in the same NAV review</strong>
        <span class="selected-file-count">0 files selected</span>
        <button type="button" data-add-more-files>＋ Add more files</button>
        <button type="button" data-add-folder>＋ Add a folder</button>
        <small>Combine administrator NAV, investor GL, side-letter rules, financial statements, bank/custodian evidence and supporting files. Large Excel sources are compacted in your browser before transport; financial data used by the NAV controller is preserved.</small>`;
      selectedFiles.insertAdjacentElement('afterend', tools);
      tools.querySelector('[data-add-more-files]').addEventListener('click', () => fileInput.click());
      tools.querySelector('[data-add-folder]').addEventListener('click', () => folderInput.click());
    }
    const count = tools.querySelector('.selected-file-count');
    if (count) count.textContent = `${staged.length} file${staged.length === 1 ? '' : 's'} · ${selectedTypeSummary()}`;
  }

  function decorateSelectedRows() {
    ensureMultiSourceTools();
    const rows = Array.from(selectedFiles.querySelectorAll('.selected-file'));
    rows.forEach((row, index) => {
      if (row.querySelector('.selected-file-remove')) return;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'selected-file-remove';
      remove.setAttribute('aria-label', `Remove ${staged[index]?.name || 'file'}`);
      remove.textContent = '×';
      remove.addEventListener('click', () => {
        staged.splice(index, 1);
        dispatchCombined(staged);
      });
      row.appendChild(remove);
    });
  }

  function ensureProgress() {
    let progress = uploadDialog.querySelector('.upload-progress');
    if (!progress) {
      progress = document.createElement('div');
      progress.className = 'upload-progress hidden';
      progress.innerHTML = '<div class="upload-progress-bar"><i></i></div><strong></strong><small></small>';
      uploadSubmit.closest('.dialog-actions')?.insertAdjacentElement('beforebegin', progress);
    }
    return progress;
  }

  function setProgress(percent, title, detail = '') {
    const progress = ensureProgress();
    progress.classList.remove('hidden', 'error');
    progress.querySelector('.upload-progress-bar i').style.width = `${Math.max(0, Math.min(100, percent))}%`;
    progress.querySelector('strong').textContent = title;
    progress.querySelector('small').textContent = detail;
  }

  function setProgressError(title, detail = '') {
    const progress = ensureProgress();
    progress.classList.remove('hidden');
    progress.classList.add('error');
    progress.querySelector('strong').textContent = title;
    progress.querySelector('small').textContent = detail;
  }

  function notify(message, isError = false) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle('error', isError);
    toast.classList.add('show');
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toast.classList.remove('show'), 3500);
  }

  function extOf(file) {
    return file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
  }

  function isExcel(file) {
    return ['xlsx', 'xls'].includes(extOf(file));
  }

  function cellValue(sheet, row, col) {
    const cell = sheet[window.XLSX.utils.encode_cell({ r: row, c: col })];
    return cell ? cell.v : null;
  }

  function compactGenericSheet(sheet) {
    const ref = sheet['!ref'];
    if (!ref) return window.XLSX.utils.aoa_to_sheet([]);
    const range = window.XLSX.utils.decode_range(ref);
    range.e.r = Math.min(range.e.r, 499);
    range.e.c = Math.min(range.e.c, 59);
    const rows = [];
    for (let r = range.s.r; r <= range.e.r; r += 1) {
      const row = [];
      for (let c = range.s.c; c <= range.e.c; c += 1) row.push(cellValue(sheet, r, c));
      rows.push(row);
    }
    return window.XLSX.utils.aoa_to_sheet(rows);
  }

  function compactInvestorGlSheet(sheet) {
    const ref = sheet['!ref'];
    if (!ref) return window.XLSX.utils.aoa_to_sheet([]);
    const range = window.XLSX.utils.decode_range(ref);
    const rows = [];
    for (let r = range.s.r; r <= range.e.r; r += 1) {
      const row = Array(36).fill(null);
      GL_KEEP_COLUMNS.forEach((col) => { row[col] = cellValue(sheet, r, col); });
      rows.push(row);
    }
    return window.XLSX.utils.aoa_to_sheet(rows);
  }

  async function compactWorkbook(file) {
    if (!window.XLSX) throw new Error('Excel optimiser did not load. Refresh the page and try again.');
    const raw = await file.arrayBuffer();
    const workbook = window.XLSX.read(raw, { type: 'array', cellDates: true, cellStyles: false, cellFormula: false });
    const out = window.XLSX.utils.book_new();

    workbook.SheetNames.forEach((sheetName) => {
      const source = workbook.Sheets[sheetName];
      const compact = sheetName.trim().toLowerCase() === INVESTOR_GL_SHEET.toLowerCase()
        ? compactInvestorGlSheet(source)
        : compactGenericSheet(source);
      window.XLSX.utils.book_append_sheet(out, compact, sheetName.slice(0, 31));
    });

    const bytes = window.XLSX.write(out, { type: 'array', bookType: 'xlsx', compression: true });
    const name = file.name.replace(/\.xls$/i, '.xlsx');
    return new File([bytes], name, {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      lastModified: file.lastModified,
    });
  }

  async function prepareForTransport(file, forceCompact) {
    if (isExcel(file) && (forceCompact || file.size > XLSX_REPACK_TRIGGER)) {
      const compact = await compactWorkbook(file);
      if (compact.size > SAFE_REQUEST_BYTES) {
        throw new Error(`${file.name} is still ${formatMb(compact.size)} after browser compaction. Split this workbook or upload a smaller export for the hackathon demo.`);
      }
      return compact;
    }
    if (file.size > SAFE_REQUEST_BYTES) {
      throw new Error(`${file.name} is ${formatMb(file.size)}. This Vercel demo accepts large Excel files by compacting them in-browser, but this ${extOf(file).toUpperCase() || 'file'} source is still above the safe request size.`);
    }
    return file;
  }

  async function requestJson(url, options, signal) {
    const response = await fetch(url, { ...options, signal, headers: { Accept: 'application/json', ...(options.headers || {}) } });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* Vercel may return an empty 413 body */ }
    if (!response.ok) {
      if (response.status === 413) throw new Error('Upload exceeded the Vercel request limit. Cherry now sends evidence in smaller transport-safe requests; refresh and retry if this was an older tab.');
      const detail = payload?.detail?.message || payload?.detail || payload?.message || `${response.status} ${response.statusText}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  function addMetadata(form, includeMetadata) {
    if (!includeMetadata) return;
    if (fundName?.value.trim()) form.append('fund_name', fundName.value.trim());
    if (reportingPeriod?.value.trim()) form.append('reporting_period', reportingPeriod.value.trim());
    if (asOfDate?.value) form.append('as_of_date', asOfDate.value);
  }

  async function sendBatch(files, caseId, includeMetadata, signal) {
    const form = new FormData();
    files.forEach((file) => form.append('files', file, file.name));
    addMetadata(form, includeMetadata);
    const endpoint = caseId
      ? `/api/fund-manager/cases/${encodeURIComponent(caseId)}/evidence`
      : '/api/fund-manager/cases';
    return requestJson(endpoint, { method: 'POST', body: form }, signal);
  }

  async function uploadTransportSafe() {
    if (!staged.length || activeUpload) return;
    uploadCancelled = false;
    activeUpload = new AbortController();
    uploadSubmit.disabled = true;
    const originalLabel = uploadSubmit.textContent;
    uploadSubmit.textContent = 'Preparing evidence…';

    try {
      const totalOriginal = staged.reduce((sum, file) => sum + file.size, 0);
      const forceCompact = totalOriginal > SAFE_REQUEST_BYTES;
      const prepared = [];

      for (let index = 0; index < staged.length; index += 1) {
        const file = staged[index];
        setProgress(
          8 + Math.round((index / Math.max(1, staged.length)) * 28),
          isExcel(file) && (forceCompact || file.size > XLSX_REPACK_TRIGGER) ? `Optimising ${file.name}` : `Preparing ${file.name}`,
          `${formatMb(file.size)} source file · processing locally before upload`,
        );
        prepared.push(await prepareForTransport(file, forceCompact));
      }

      if (uploadCancelled) return;
      const preparedTotal = prepared.reduce((sum, file) => sum + file.size, 0);
      let caseId = sessionStorage.getItem('cherryCfoNavCaseId');
      let response = null;

      if (preparedTotal <= SAFE_REQUEST_BYTES) {
        setProgress(48, 'Uploading evidence pack', `${prepared.length} source${prepared.length === 1 ? '' : 's'} · ${formatMb(preparedTotal)} transport size`);
        response = await sendBatch(prepared, caseId, !caseId, activeUpload.signal);
        caseId = response.case_id || caseId;
      } else {
        for (let index = 0; index < prepared.length; index += 1) {
          const file = prepared[index];
          setProgress(
            45 + Math.round((index / prepared.length) * 35),
            `Uploading ${index + 1} of ${prepared.length}`,
            `${file.name} · ${formatMb(file.size)} · sent separately to avoid request-size failures`,
          );
          response = await sendBatch([file], caseId, !caseId, activeUpload.signal);
          caseId = response.case_id || caseId;
          if (!caseId) throw new Error('Cherry did not return a NAV review case id after upload.');
        }
      }

      if (!caseId) throw new Error('Cherry could not create a NAV review case from the uploaded evidence.');
      sessionStorage.setItem('cherryCfoNavCaseId', caseId);

      setProgress(84, 'Evidence classified', 'Assessing which NAV controls are supported by the supplied sources…');
      response = await requestJson(
        `/api/fund-manager/cases/${encodeURIComponent(caseId)}/nav/readiness`,
        { method: 'POST' },
        activeUpload.signal,
      );

      sessionStorage.setItem('cherryCfoNavCaseSnapshot', JSON.stringify(response));
      setProgress(100, 'NAV analysis ready', 'Opening the control map…');
      uploadSubmit.textContent = 'Ready';
      setTimeout(() => {
        if (uploadDialog.open) uploadDialog.close();
        window.location.reload();
      }, 450);
    } catch (error) {
      if (error?.name === 'AbortError' || uploadCancelled) return;
      setProgressError('Upload stopped', error.message || 'Unable to process the evidence pack.');
      notify(error.message || 'Unable to process the evidence pack.', true);
      uploadSubmit.disabled = false;
      uploadSubmit.textContent = originalLabel;
    } finally {
      activeUpload = null;
      if (!uploadCancelled && uploadSubmit.textContent !== 'Ready' && !uploadDialog.querySelector('.upload-progress.error')) {
        uploadSubmit.disabled = !staged.length;
        uploadSubmit.textContent = originalLabel;
      }
    }
  }

  /* Merge multiple native-picker batches instead of replacing the earlier selection. */
  fileInput.addEventListener('change', () => {
    const current = Array.from(fileInput.files || []);
    if (internalDispatch) {
      internalDispatch = false;
      staged = dedupe(current);
    } else {
      staged = dedupe([...staged, ...current]);
      setInputFiles(staged);
    }
    setTimeout(decorateSelectedRows, 0);
  }, true);

  folderInput.addEventListener('change', () => {
    const folderFiles = Array.from(folderInput.files || []);
    if (folderFiles.length) dispatchCombined([...staged, ...folderFiles]);
    folderInput.value = '';
  });

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest?.('[data-open-upload], #top-upload');
    if (trigger && !uploadDialog.open) staged = [];
  }, true);

  /* Replace the core one-shot multipart uploader. This avoids Vercel 413 responses and lets us
     cancel an in-flight analysis cleanly rather than showing a late 413 after the dialog closes. */
  uploadSubmit.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    uploadTransportSafe();
  }, true);

  uploadDialog.addEventListener('click', (event) => {
    const cancel = event.target.closest?.('.dialog-close, .dialog-actions .secondary');
    if (!cancel || !activeUpload) return;
    uploadCancelled = true;
    activeUpload.abort();
  }, true);

  uploadDialog.addEventListener('close', () => {
    if (activeUpload) {
      uploadCancelled = true;
      activeUpload.abort();
    }
    staged = [];
    folderInput.value = '';
    const tools = uploadDialog.querySelector('.multi-source-tools');
    if (tools) tools.remove();
    const progress = uploadDialog.querySelector('.upload-progress');
    if (progress) progress.remove();
  });

  boardStage.addEventListener('drop', (event) => {
    const dropped = Array.from(event.dataTransfer?.files || []);
    if (!dropped.length) return;
    staged = dedupe(dropped);
    setTimeout(decorateSelectedRows, 0);
  }, true);

  function positionHero() {
    layoutFrame = null;
    if (emptyState.classList.contains('hidden')) return;
    const x = boardStage.scrollLeft + (boardStage.clientWidth / 2);
    const visibleHeight = boardStage.clientHeight;
    const y = boardStage.scrollTop + Math.max(245, Math.min(visibleHeight * 0.40, 350));
    emptyState.style.left = `${Math.round(x)}px`;
    emptyState.style.top = `${Math.round(y)}px`;
  }

  function scheduleHero() {
    if (layoutFrame !== null) return;
    layoutFrame = requestAnimationFrame(positionHero);
  }

  boardStage.addEventListener('scroll', scheduleHero, { passive: true });
  window.addEventListener('resize', scheduleHero);
  new MutationObserver(scheduleHero).observe(emptyState, { attributes: true, attributeFilter: ['class'] });

  scheduleHero();
})();