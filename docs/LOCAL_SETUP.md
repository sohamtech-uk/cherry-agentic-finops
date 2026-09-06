# Cherry CFO — Local setup for the Syndicate branch

This guide runs the **Syndicate NAV Quality Controller** locally from `ui/syndicate-cfo-canvas`.

Public demo: https://cherry-cfo-canvas.vercel.app

## 1. Prerequisites

Required:

- Git
- Python 3.11+
- `pip`

Recommended:

- Python 3.12
- Node.js for browser JavaScript checks
- Docker for the container quality gate
- Google Cloud CLI only when using Vertex AI locally

## 2. Clone and select the Syndicate branch

```bash
git clone https://github.com/sohamtech-uk/cherry-agentic-finops.git
cd cherry-agentic-finops
git fetch origin
git switch ui/syndicate-cfo-canvas
```

Confirm:

```bash
git branch --show-current
```

Expected:

```text
ui/syndicate-cfo-canvas
```

Do not merge this branch to `main` as part of the hackathon workflow.

## 3. Python environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 4. Environment file

```bash
cp .env.example .env
```

A minimal local configuration can use in-memory state:

```env
CHERRY_ENVIRONMENT=local
CHERRY_PUBLIC_BASE_URL=http://localhost:8080
CHERRY_PERSISTENCE_BACKEND=memory
```

The NAV case store is ephemeral in memory and resets when the process stops.

## 5. Model-backed agent stages

Deterministic NAV controls do not need a model provider. Agentic planning/investigation stages do.

### Gemini Developer API

```env
GOOGLE_GENAI_USE_VERTEXAI=false
GOOGLE_API_KEY=YOUR_LOCAL_KEY
```

### Vertex AI

```env
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
```

Then authenticate Application Default Credentials:

```bash
gcloud auth application-default login
```

Never commit populated secrets.

## 6. Neatlogs observability — optional

The branch includes Neatlogs instrumentation for agent tracing.

To enable export:

```env
NEATLOGS_API_KEY=YOUR_PROJECT_KEY
NEATLOGS_WORKFLOW_NAME=cherry-cfo-syndicate
```

Leave the key empty to run without trace export. Observability is not financial authority and should not change a control result.

## 7. Start the application

```bash
uvicorn app.api:app --reload --port 8080
```

or:

```bash
make run
```

Open:

```text
http://localhost:8080
http://localhost:8080/api/docs
```

The root page on this branch is the Cherry CFO NAV canvas workbench.

## 8. Judge-facing NAV API

The main case workflow is:

```text
POST /api/fund-manager/cases
POST /api/fund-manager/cases/{case_id}/evidence
GET  /api/fund-manager/cases/{case_id}
POST /api/fund-manager/cases/{case_id}/nav/readiness
POST /api/fund-manager/cases/{case_id}/nav/reconcile
POST /api/fund-manager/cases/{case_id}/nav/review
POST /api/fund-manager/cases/{case_id}/nav/decision
```

Typical local flow:

1. upload one or more evidence sources;
2. inspect classification;
3. call NAV readiness;
4. run deterministic controls if readiness permits;
5. run agent review when a reconciliation result exists;
6. record a human decision.

## 9. Evidence that supports the NAV controller

The workbench accepts mixed files, but a file is useful to a control only when it is recognised and passes its input contract.

Useful evidence families include:

- administrator NAV summary;
- investor-level GL;
- structured side-letter rules;
- NAV workbooks;
- financial statements;
- supporting PDF / Excel / CSV / JSON evidence.

A supported investor-level GL can enable a partial review without an administrator NAV summary. Missing evidence remains explicit.

## 10. Large Excel files

The public Vercel UI includes browser-side transport optimisation because hosted request bodies have size limits.

A local Uvicorn run does not use that Vercel transport path, so local testing is preferable when you need to inspect large raw workbooks without browser compaction.

The hosted optimisation is not a financial shortcut: after transport, the backend still classifies and validates the structured workbook before enabling NAV controls.

## 11. Optional persistence

Memory is simplest for the hackathon.

Firestore-backed case persistence is available where configured:

```env
CHERRY_PERSISTENCE_BACKEND=firestore
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
CHERRY_FUND_MANAGER_FIRESTORE_COLLECTION=fund_manager_cases
```

You will need Google Application Default Credentials with the appropriate permissions.

## 12. Quality gates

Run before submission or a release candidate:

```bash
ruff check .
ruff format --check .
mypy app agents
pytest
python -m compileall -q app agents
node --check app/static/cfo_canvas.js
node --check app/static/cfo_canvas_patch.js
docker build --tag cherry-cfo:test .
```

## 13. Troubleshooting

### Canvas loads but agent review fails

Check model configuration. The deterministic evidence/readiness/control path can still be demonstrated without model access.

### Evidence uploads but readiness remains `needs_input`

Inspect classification in the UI or case payload. A recognised but unsupported/invalid file does not count as the required NAV input. Add a supported administrator NAV summary or investor-level GL.

### Hosted demo reports a request-size problem

Hard refresh the Vercel page so the current transport-safe uploader is loaded. Large Excel evidence is optimised in the browser and may be sent as separate requests.

### An Excel file is classified as unknown

The classifier inspects workbook structure. Check that expected sheets/headers are present; filenames alone are not treated as proof.

### `NEATLOGS_API_KEY` is absent

That is fine. Trace export is optional and the finance workflow must continue without it.

## 14. Hackathon provenance

The official Syndicate start boundary and AO session record are in:

- `SYNDICATE_BUILD_LOG.md`
- `PREEXISTING_CODE.md`

The source tree still contains pre-existing modules with historical private-markets names, including `ylookup_*`. Those remain for compatibility; the current branch documentation and judge-facing experience are **Syndicate / Cherry CFO NAV Quality Controller**.
