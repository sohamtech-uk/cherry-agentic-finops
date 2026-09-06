(() => {
  'use strict';

  const fileInput = document.getElementById('file-input');
  const uploadDialog = document.getElementById('upload-dialog');
  const selectedFiles = document.getElementById('selected-files');
  const boardStage = document.getElementById('board-stage');
  const emptyState = document.getElementById('empty-state');

  if (!fileInput || !uploadDialog || !selectedFiles || !boardStage || !emptyState) return;

  let staged = [];
  let internalDispatch = false;
  let layoutFrame = null;

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
        <small>Combine administrator NAV, investor GL, side-letter rules, financial statements, bank/custodian evidence and supporting files. You can select several batches before uploading.</small>`;
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

  /* The browser normally replaces a file selection when the picker is opened again.
     Merge each new batch before the original canvas listener receives the change event. */
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

  /* Reset only when starting a fresh dialog session. Re-opening the native file picker inside
     the dialog must preserve earlier selections. */
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest?.('[data-open-upload], #top-upload');
    if (trigger && !uploadDialog.open) staged = [];
  }, true);

  uploadDialog.addEventListener('close', () => {
    staged = [];
    folderInput.value = '';
    const tools = uploadDialog.querySelector('.multi-source-tools');
    if (tools) tools.remove();
  });

  /* Dragging a batch onto the canvas is also a valid first source. The core listener creates
     the dialog and displays those files; mirror them here so the user can add another batch. */
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
