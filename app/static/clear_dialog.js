(() => {
  "use strict";

  const DIALOG_ID = "clear-data-dialog";
  const STYLE_ID = "clear-data-dialog-styles";

  const q = (selector) => document.querySelector(selector);

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
      @media (max-width: 520px) {
        .clear-dialog-actions {
          flex-direction: column-reverse;
        }
        .clear-dialog-actions button {
          width: 100%;
        }
      }
    `;
    document.head.appendChild(style);
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
          <li>temporary server workflow memory created for the current session.</li>
        </ul>
        <p class="clear-dialog-warning">This action cannot be undone.</p>
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
    const token = q("#upload-token")?.value.trim() || "";
    const headers = token ? { "X-Cherry-Demo-Token": token } : {};
    dialog.close();
    if (typeof loading === "function") loading(true);

    try {
      const response = await fetch("/api/session/clear-memory", { method: "POST", headers });
      let body = {};
      try { body = await response.json(); } catch { body = {}; }
      if (!response.ok) {
        const detail = typeof body.detail === "string"
          ? body.detail
          : body.detail?.message || `${response.status} ${response.statusText}`;
        throw new Error(detail);
      }

      if (typeof resetEvidenceWorkspace === "function") resetEvidenceWorkspace();
      const count = Number(body.cleared_workflow_records || 0);
      const message = `Uploaded data and memory cleared · ${count} server workflow record${count === 1 ? "" : "s"} removed.`;
      if (typeof toast === "function") toast(message);
    } catch (error) {
      if (typeof toast === "function") toast(error.message, true);
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

  document.addEventListener("DOMContentLoaded", bindCustomClearDialog);
})();
