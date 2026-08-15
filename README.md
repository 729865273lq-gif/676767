# AI Foreign Trade Sales Platform

V1 is a multi-tenant sales workbench for evidence-backed prospect discovery and human-approved email outreach.

## Local setup

1. Copy `.env.example` to `.env` and replace all placeholder secrets.
2. Create the API virtual environment and install dependencies:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   ```

3. Install the web dependencies:

   ```powershell
   cd frontend
   npm.cmd install
   ```

4. Start the full local runtime (web workbench, API, worker, PostgreSQL with pgvector, Redis, and MinIO):

   ```powershell
   docker compose up --build
   ```

The workbench is available at `http://localhost:3000`, and the API health endpoint is `http://localhost:8000/health`.

## Outbound email

Email drafts are never sent automatically. After a draft is reviewed and approved, the send action uses SMTP credentials from `.env`:

```powershell
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=sender@example.com
SMTP_PASSWORD=your-smtp-password
SMTP_FROM_EMAIL=sender@example.com
SMTP_FROM_NAME=Trade Axis
SMTP_USE_TLS=true
```

For Gmail or Outlook, use an app password or SMTP credential for local development. Production should move to OAuth before broad use.

## Customer development APIs

The dashboard shows a read-only API readiness panel for the customer development flow. Add keys to `.env` as you connect providers:

```powershell
BOCHA_API_KEY=...
GOOGLE_CSE_API_KEY=...
GOOGLE_CSE_CX=...
GOOGLE_PLACES_API_KEY=...
TOMTOM_API_KEY=...
SERPAPI_API_KEY=...
DATAFORSEO_LOGIN=...
DATAFORSEO_PASSWORD=...
APOLLO_API_KEY=...
HUNTER_API_KEY=...
ZEROBOUNCE_API_KEY=...
NEVERBOUNCE_API_KEY=...
```

Use the search-source panel to enable or disable customer search providers per workspace. OpenStreetMap is enabled by default for low-volume, user-triggered global business search and requires no API key. TomTom adds overseas POI results with public phone and website fields after `TOMTOM_API_KEY` is configured. Create a free key at `https://developer.tomtom.com/`, add it to `.env`, and restart the API. Bocha and Google Programmable Search cover public web results. Google Places remains optional. The public-contact scan reads mail, phone, WhatsApp, LinkedIn, Facebook, Instagram, TikTok, and other public links from a company's website, while Hunter can supplement named email contacts when configured. All outreach remains manual.

## Knowledge Base

The knowledge base stores per-workspace documents (PDF, DOCX, XLSX) as searchable chunks. Admins upload documents, and members search them with semantic similarity. Ingestion requires a configured OpenAI-compatible embedding provider:

```powershell
EMBEDDING_API_BASE=...
EMBEDDING_API_KEY=...
EMBEDDING_MODEL=BAAI/bge-m3
```

`EMBEDDING_MODEL` defaults to `BAAI/bge-m3`, which produces 1024-dimensional vectors. Uploaded files are stored in the MinIO bucket `foreign-trade`, while chunk text and vector embeddings are persisted in PostgreSQL (pgvector).

## Verification

On Windows, run the component commands directly:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check app tests

cd ..\frontend
npm.cmd run test:e2e
npm.cmd run lint
```

On systems with `make`, `make up`, `make test-backend`, `make test-frontend`, and `make lint` provide the same actions.
