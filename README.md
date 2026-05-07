# Customer Onboarding Agent

ERP-style customer onboarding dashboard with a 9-stage agent flow. Step 1 (Customer Application Initiation) is fillable end-to-end; Steps 2-9 are rendered as locked placeholders.

## Architecture

- **Postgres 16** — runs in Docker, exposed on host port `5433` (host port `5432` is reserved for the developer's local postgres)
- **postgres-mcp** ([crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)) — runs in Docker, SSE transport at `http://localhost:8001/sse`
- **FastAPI backend** — runs on host (`localhost:8000`)
- **React + Vite + shadcn frontend** — runs on host (`localhost:5173`)

## Prerequisites

- Docker Desktop
- Python 3.11+
- Node.js 20+

## Running locally

```powershell
# 1. Start the database stack
docker compose up -d
docker compose ps   # both services should be running / healthy

# 2. Backend (new terminal)
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Endpoints

- `GET  /api/health`
- `POST /api/applications`            (multipart: form fields + `pan_file` + `aadhaar_file`)
- `GET  /api/applications`
- `GET  /api/applications/{id}`
- `GET  /api/applications/{id}/documents/{doc_type}`     (`doc_type` = `pan` | `aadhaar`)

## The 9-stage flow

| # | Stage                            | Status        |
|---|----------------------------------|---------------|
| 1 | Customer Application Initiation  | Implemented   |
| 2 | Document Verification            | Placeholder   |
| 3 | KYC Agent                        | Placeholder   |
| 4 | Eligibility                      | Placeholder   |
| 5 | Pricing                          | Placeholder   |
| 6 | Regulatory Disclosure            | Placeholder   |
| 7 | Account Creation                 | Placeholder   |
| 8 | Welcome                          | Placeholder   |
| 9 | Exception Router                 | Placeholder   |

## postgres-mcp

The MCP server is reachable at `http://localhost:8001/sse`. Point any MCP-capable client at it to query the onboarding DB. It runs with `--access-mode=unrestricted` for development; restrict in production.
