# Cherry FundOps — Local Setup Guide

This guide explains how to run the Cherry FundOps website and API locally for development, demos, and testing.

## 1. What runs locally

The repository contains one FastAPI application that serves both the browser UI and the API. The default local configuration uses in-memory persistence, so no database is required for a basic setup.

Local development can run in two modes:

- **Deterministic/local mode** — suitable for synthetic demos, deterministic controls, static UI, API documentation, and many tests. Gemini credentials are optional.
- **Agentic mode** — required for Fund Manager planning, execution orchestration, and investigation stages that call Google ADK/Gemini.

The financial boundary is unchanged in both modes: Cherry FundOps performs review and decision support only; it does not initiate payments or silently modify an official NAV or ledger.

## 2. Prerequisites

Required:

- Git
- Python **3.11 or newer**
- `pip`

Recommended:

- Python 3.12, matching the repository Docker image
- `make` for convenience commands
- Node.js for the browser JavaScript syntax quality gate
- Docker Desktop or Docker Engine for container-based local runs
- Google Cloud CLI only if you want to use Vertex AI locally

Check your versions:

```bash
git --version
python3 --version
python3 -m pip --version
```

## 3. Clone the repository

Using SSH:

```bash
git clone git@github.com:sohamtech-uk/cherry-agentic-finops.git
cd cherry-agentic-finops
```

Or using HTTPS:

```bash
git clone https://github.com/sohamtech-uk/cherry-agentic-finops.git
cd cherry-agentic-finops
```

## 4. Create a Python virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

## 5. Install the application

Install the application with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Equivalent convenience command:

```bash
make install
```

The project requires Python 3.11+ and installs FastAPI, Google ADK, Google Gen AI, OpenPyXL, pypdf, ReportLab, Firestore/Storage clients, testing tools, Ruff, and mypy from `pyproject.toml`.

## 6. Create the local environment file

Copy the checked-in example:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

For the simplest local run, the important values are:

```env
CHERRY_ENVIRONMENT=local
CHERRY_PUBLIC_BASE_URL=http://localhost:8080
CHERRY_PERSISTENCE_BACKEND=memory
CHERRY_GEMINI_MODEL=gemini-3.7-flash
```

With `CHERRY_PERSISTENCE_BACKEND=memory`, Fund Manager cases stay only in the running Python process and are lost when the server restarts.

## 7. Gemini / Google configuration

### Option A — run without Gemini credentials

You can leave the Google fields empty when you only need deterministic demos, the website shell, API docs, and non-Gemini functionality.

```env
GOOGLE_CLOUD_PROJECT=
GOOGLE_API_KEY=
```

Some Fund Manager agentic stages will not be able to complete without a configured Gemini provider.

### Neatlogs tracing

To send Google ADK and Gemini agent traces to the project's Neatlogs workspace, set the project
API key in the ignored `.env` file:

```env
NEATLOGS_API_KEY=YOUR_PROJECT_KEY
NEATLOGS_WORKFLOW_NAME=fund-manager-control-review
```

Leave `NEATLOGS_API_KEY` empty to run without exporting traces. Never commit a populated key.

### Option B — Gemini Developer API

Set:

```env
GOOGLE_GENAI_USE_VERTEXAI=false
GOOGLE_API_KEY=YOUR_LOCAL_KEY
```

Never commit the populated `.env` file or API key.

### Option C — Vertex AI

Set:

```env
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
```

Authenticate Application Default Credentials:

```bash
gcloud auth application-default login
```

Your Google Cloud identity/project must have permission to use the configured Gemini model.

## 8. Upload protection in local mode

The repository includes `CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN` for protected deployments.

For normal local development, it can remain empty:

```env
CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN=
```

Do not copy a production upload token into screenshots, sample files, commits, or documentation.

## 9. Optional services

### Firestore persistence

The default local setup uses memory and requires no database.

To exercise Firestore-backed Fund Manager cases:

```env
CHERRY_PERSISTENCE_BACKEND=firestore
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
CHERRY_FUND_MANAGER_FIRESTORE_COLLECTION=fund_manager_cases
```

You will also need valid Google Application Default Credentials.

### FundOps Agent Studio

Agent Studio is optional. If it is not configured, Cherry should continue its local strict control analysis and report enrichment as unavailable.

For a local/non-GCP Agent Studio service:

```env
FUNDOPS_STUDIO_API_URL=http://localhost:PORT
FUNDOPS_STUDIO_API_TOKEN=YOUR_LOCAL_TOKEN
FUNDOPS_STUDIO_TIMEOUT_SECONDS=25
```

For a private Cloud Run Agent Studio service, use the service URL and audience instead:

```env
FUNDOPS_STUDIO_API_URL=https://SERVICE_URL
FUNDOPS_STUDIO_AUDIENCE=https://SERVICE_URL
```

### Cherry Money read-only bridge

Optional:

```env
CHERRY_MONEY_API_URL=https://cherrymoney.co.uk
CHERRY_MONEY_API_TOKEN=
```

The private-markets workflow must remain read-only against Cherry Money.

## 10. Start the application

Recommended development command:

```bash
uvicorn app.api:app --reload --port 8080
```

Or:

```bash
make run
```

You should see Uvicorn listening on `http://127.0.0.1:8080` or `http://localhost:8080`.

## 11. Useful local URLs

Open these in a browser:

| Purpose | URL |
| --- | --- |
| Cherry FundOps website | http://localhost:8080 |
| Fund Manager section | http://localhost:8080/#fund-manager |
| API documentation | http://localhost:8080/api/docs |
| Main service health | http://localhost:8080/health |
| Fund Manager health | http://localhost:8080/api/fund-manager/health |
| Private-markets health | http://localhost:8080/api/private-markets/health |
| Integration health | http://localhost:8080/api/private-markets/integration/health |
| NAV Quality health | http://localhost:8080/api/nav-quality/health |
| Statement Review health | http://localhost:8080/api/statement-review/health |

Quick health check:

```bash
curl http://localhost:8080/health
```

Expected shape:

```json
{"status":"ok","service":"cherry-agent","version":"0.1.0"}
```

## 12. Fund Manager local workflow

The staged Fund Manager experience is:

```text
Upload evidence
  → Evidence Review
  → Review Plan
  → Control Results
  → Findings Review
  → Human Decision
  → Final report / Start new case
```

The planning and investigation stages are agentic, while financial calculations and reconciliations remain in deterministic tools.

Typical accepted local evidence includes PDF, XLSX, CSV, JSON, TXT, and ZIP batches, depending on the workflow being exercised.

## 13. Generate synthetic backup fixtures

```bash
make ylookup-fixtures
```

This generates the checked demo fixture shapes used by the private-markets workflows.

## 14. Run with Docker

The repository Docker image uses Python 3.12 and starts Uvicorn on port 8080.

Using Docker Compose:

```bash
docker compose up --build
```

Then open:

```text
http://localhost:8080
```

Stop with:

```bash
docker compose down
```

The compose configuration forces local mode and in-memory persistence.

## 15. Quality checks before opening a PR

Run the same important checks used by CI:

```bash
ruff check .
ruff format --check .
mypy app agents
pytest
python -m compileall -q app agents
node --check app/static/app.js
```

The repository also checks browser JavaScript and container buildability in CI.

Build the container locally:

```bash
docker build --tag cherry-agent:test .
```

Or use the Make targets:

```bash
make lint
make test
```

## 16. Common problems

### `python` or `python3` is not found

Install Python 3.11+ and reopen the terminal. On Windows, try `py` instead of `python3`.

### The website opens but a Fund Manager agent step fails

Check whether Gemini is configured. Fund Manager planning, control orchestration, and exception investigation use Google ADK/Gemini. Deterministic-only features can still work without those credentials.

### Vertex AI authentication error

Run:

```bash
gcloud auth application-default login
```

Then confirm the correct project is configured in `.env`.

### Port 8080 is already in use

Run on another port:

```bash
uvicorn app.api:app --reload --port 8081
```

If you change the port, update `CHERRY_PUBLIC_BASE_URL` accordingly.

### Firestore errors locally

Switch back to the no-dependency local store:

```env
CHERRY_PERSISTENCE_BACKEND=memory
```

Restart Uvicorn after changing `.env`.

### Stale browser JavaScript or CSS

Use a hard refresh after rebuilding/restarting:

- macOS Chrome: `Cmd + Shift + R`
- Windows/Linux Chrome: `Ctrl + Shift + R`

## 17. Development safety notes

- Keep `.env` local and never commit secrets.
- Do not use production fund data for local development unless explicitly authorised and appropriately protected.
- Prefer synthetic/anonymised evidence for demos and tests.
- Cherry FundOps is a control/review system; do not extend local demos to initiate payments.
- Treat report outputs as decision-support evidence, not as automatic ledger or NAV writes.

## 18. Next documentation

For the website layout, system architecture, and staged demo workflow, see [Website, System & Workflow Guide](WEBSITE_SYSTEM_AND_WORKFLOW.md).
