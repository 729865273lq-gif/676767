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
