(() => {
  "use strict";

  const DIALOG_ID = "clear-data-dialog";
  const STYLE_ID = "clear-data-dialog-styles";

  const q = (selector) => document.querySelector(selector);

  function todayIso() {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 10);
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${DIALOG_ID} {
        width: min(520px, calc(100vw - 32px));
        padding: 0;
        border: 1px solid #d6d2c8;
        border-radius: 20px;
        color: #17201d;
        background: #fffdf8;
        box-shadow: 0 30px 90px rgba(8, 35, 29, .28);
      }
      #${DIALOG_ID}::backdrop {
        background: rgba(7, 35, 29, .72);
        backdrop-filter: blur(3px);
      }
      .clear-dialog-head {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 20px 22px;
        color: #fff;
        background: #123c32;
      }
      .clear-dialog-mark {
        width: 36px;
        height: 36px;
        display: grid;
        place-items: center;
        flex: 0 0 auto;
        border-radius: 10px 10px 10px 3px;
        color: #123c32;
        background: #bdf28d;
        font-weight: 900;
      }
      .clear-dialog-head strong {
        font-size: 16px;
        letter-spacing: -.01em;
      }
      .clear-dialog-body {
        padding: 24px 24px 8px;
      }
      .clear-dialog-body h3 {
        margin: 0;
        font-family: Georgia, "Times New Roman", serif;
        font-size: 28px;
        font-weight: 500;
        line-height: 1.12;
        letter-spacing: -.025em;
      }
      .clear-dialog-body > p {
        margin: 13px 0 0;
        color: #56615c;
        font-size: 13px;
        line-height: 1.55;
      }
      .clear-dialog-list {
        margin: 17px 0 0;
        padding: 14px 16px 14px 32px;
        border: 1px solid #e3dfd6;
        border-radius: 12px;
        color: #4d5b56;
        background: #f7f4ed;
        font-size: 12px;
      }
      .clear-dialog-list li + li {
        margin-top: 5px;
      }
      .clear-dialog-warning {
        margin: 14px 0 0 !important;
        color: #8c2e1d !important;
        font-weight: 800;
      }
      .clear-dialog-safety {
        margin: 8px 0 0 !important;
        color: #64716c !important;
        font-size: 11px !important;
      }
      .clear-dialog-actions {
        display: flex;
        justify-content: flex-end;
        gap: 10px;
        padding: 20px 24px 24px;
      }
      .clear-dialog-actions button {
        min-height: 44px;
        padding: 0 16px;
        border-radius: 10px;
        font: inherit;
        font-size: 12px;
        font-weight: 850;
        cursor: pointer;
      }
      .clear-dialog-cancel {
        color: #35564c;
        border: 1px solid #cfd8d2;
        background: #f7f4ed;
      }
      .clear-dialog-confirm {
        color: #fff;
        border: 1px solid #9b3d29;
        background: #9b3d29;
      }
      .clear-dialog-confirm:hover {
        background: #833220;
      }

      .control-date-field {
        border-color: #b9ccc3 !important;
        background: linear-gradient(145deg, #f8fbf7, #eef6f0) !important;
      }
      .control-date-field > span {
        color: #123c32 !important;
      }
      .control-date-field > span small {
        color: #587168;
        font-size: .82em;
        font-weight: 750;
      }
      .control-date-row {
        display: flex;
        align-items: stretch;
        gap: 8px;
        margin-top: 8px;
      }
      .control-date-row input[type="date"] {
        min-width: 0;
        min-height: 46px;
        flex: 1 1 auto;
        padding: 0 12px;
        color: #17201d;
        border: 1px solid #b8c9c0;
        border-radius: 10px;
        background: #fffdf8;
        font-size: 13px;
        font-weight: 750;
        outline: none;
      }
      .control-date-row input[type="date"]:focus {
        border-color: #4f7d6d;
        box-shadow: 0 0 0 3px rgba(79, 125, 109, .12);
      }
      .control-date-today {
        min-height: 46px;
        padding: 0 13px;
        color: #123c32;
        border: 1px solid #b8c9c0;
        border-radius: 10px;
        background: #e9f8dc;
        font: inherit;
        font-size: 11px;
        font-weight: 850;
        cursor: pointer;
        white-space: nowrap;
      }
      .control-date-today:hover {
        border-color: #709687;
        background: #def2cc;
      }
      .control-date-help {
        display: block;
        margin-top: 8px;
        color: #61706a !important;
        font-size: 9px !important;
        line-height: 1.45;
      }

      @media (max-width: 520px) {
        .clear-dialog-actions {
          flex-direction: column-reverse;
        }
        .clear-dialog-actions button {
          width: 100%;
        }
        .control-date-row {
          flex-direction: column;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function enhanceControlDate() {
    const input = q("#as-of-input");
    if (!input) return;
    const label = input.closest("label");
    if (!label) return;

    injectStyles();
    label.classList.add("control-date-field");
    input.required = false;
    input.removeAttribute("required");
    input.setAttribute("aria-describedby", "control-date-help");

    const title = [...label.children].find((child) => child.tagName === "SPAN");
    if (title) title.innerHTML = "Control date <small>(optional)</small>";

    if (!input.parentElement?.classList.contains("control-date-row")) {
      const row = document.createElement("div");
      row.className = "control-date-row";
      input.parentNode.insertBefore(row, input);
      row.appendChild(input);

      const todayButton = document.createElement("button");
      todayButton.type = "button";
      todayButton.className = "control-date-today";
      todayButton.textContent = "Use today";
      todayButton.addEventListener("click", () => {
        input.value = todayIso();
        input.focus();
      });
      row.appendChild(todayButton);
    }

    if (!q("#control-date-help")) {
      const help = document.createElement("small");
      help.id = "control-date-help";
      help.className = "control-date-help";
      help.textContent = "Optional · Used for due-date and ageing checks. Clear it to skip time-based controls.";
      label.appendChild(help);
    }

    const originalHardcodedDate = "2026-09-05";
    if (!input.value || input.value === originalHardcodedDate) input.value = todayIso();

    const form = q("#upload-form");
    if (form && form.dataset.controlDateResetBound !== "true") {
      form.dataset.controlDateResetBound = "true";
      form.addEventListener("reset", () => {
        window.setTimeout(() => { input.value = todayIso(); }, 0);
      });
    }
  }

  function ensureDialog() {
    let dialog = document.getElementById(DIALOG_ID);
    if (dialog) return dialog;

    injectStyles();
    dialog = document.createElement("dialog");
    dialog.id = DIALOG_ID;
    dialog.setAttribute("aria-labelledby", "clear-dialog-title");
    dialog.setAttribute("aria-describedby", "clear-dialog-description");
    dialog.innerHTML = `
      <div class="clear-dialog-head">
        <span class="clear-dialog-mark" aria-hidden="true">C</span>
        <strong>Cherry FundOps says</strong>
      </div>
      <div class="clear-dialog-body">
        <h3 id="clear-dialog-title">Are you sure you want to clear uploaded data and memory?</h3>
        <p id="clear-dialog-description">This will reset the current evidence workspace and remove:</p>
        <ul class="clear-dialog-list">
          <li>the PDF, Excel and JSON files currently selected in this browser;</li>
          <li>the rendered analysis and exception results on this page; and</li>
          <li>temporary server workflow memory when this deployment uses an in-memory backend.</li>
        </ul>
        <p class="clear-dialog-warning">This action cannot be undone in the current browser session.</p>
        <p class="clear-dialog-safety">No upload token is required. Persistent audit/workflow records are not deleted.</p>
      </div>
      <div class="clear-dialog-actions">
        <button class="clear-dialog-cancel" type="button">Cancel</button>
        <button class="clear-dialog-confirm" type="button">Yes, clear data &amp; memory</button>
      </div>
    `;
    document.body.appendChild(dialog);

    q(`#${DIALOG_ID} .clear-dialog-cancel`).addEventListener("click", () => dialog.close());
    q(`#${DIALOG_ID} .clear-dialog-confirm`).addEventListener("click", () => clearDataAndMemory(dialog));
    return dialog;
  }

  async function clearDataAndMemory(dialog) {
    dialog.close();

    // Clear the browser workspace first. This must never depend on a protected upload token.
    if (typeof resetEvidenceWorkspace === "function") resetEvidenceWorkspace();
    if (typeof loading === "function") loading(true);

    try {
      const response = await fetch("/api/session/clear-memory", { method: "POST" });
      let body = {};
      try { body = await response.json(); } catch { body = {}; }
      if (!response.ok) {
        const detail = typeof body.detail === "string"
          ? body.detail
          : body.detail?.message || `${response.status} ${response.statusText}`;
        throw new Error(detail);
      }

      const memoryBacked = body.persistence_backend === "memory";
      const count = Number(body.cleared_workflow_records || 0);
      const message = memoryBacked
        ? `Uploaded data and session memory cleared · ${count} temporary workflow record${count === 1 ? "" : "s"} removed.`
        : "Uploaded data and current analysis cleared. Persistent audit records were left unchanged.";
      if (typeof toast === "function") toast(message);
    } catch (error) {
      const message = "Uploaded data and current analysis were cleared in this browser. Server memory reset could not be confirmed.";
      if (typeof toast === "function") toast(message, true);
      console.warn("Cherry FundOps clear-memory request failed:", error);
    } finally {
      if (typeof loading === "function") loading(false);
    }
  }

  function bindCustomClearDialog() {
    const button = q("#clear-upload-memory");
    if (!button || button.dataset.customClearDialog === "true") return;

    if (typeof clearUploadedMemory === "function") {
      button.removeEventListener("click", clearUploadedMemory);
    }

    button.dataset.customClearDialog = "true";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const dialog = ensureDialog();
      if (typeof dialog.showModal === "function") dialog.showModal();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    enhanceControlDate();
    bindCustomClearDialog();
  });
})();
