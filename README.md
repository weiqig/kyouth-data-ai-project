# AI Document Processing Pipeline

## Overview

A **containerized full-stack application**: Next.js frontend, FastAPI backend, Celery workers, and provider-based AI extraction — all run together with Docker Compose.

The platform transforms unstructured business documents into standardized, validated and reviewable records. It combines deterministic parsing, configurable document templates, AI-assisted extraction, validation, asynchronous processing and human review. AI assists reviewers — it never replaces business rules or human approval.

---

## Key Features

- Asynchronous processing using FastAPI, Celery and Redis
- PostgreSQL as the system of record
- Original file preservation and download
- Auto Detect document mode
- Free Extraction mode (template-free AI extraction)
- Configurable template-based extraction
- Deterministic template-labelled extraction
- Provider-agnostic AI (Gemini, Claude, Ollama, Mock, OpenAI-compatible)
- AI Review Assistant
- Validation engine
- Human review workflow
- Source highlighting and document preview
- Audit trail
- Automatic Celery recovery workflows
- Dashboard and searchable database records

---

## Processing Modes

### Auto Detect (Recommended)

Automatically classifies the uploaded document and applies the most suitable template. If no suitable template is found, processing falls back to Free Extraction.

### Free Extraction

Processes the uploaded document without using any predefined template. The parser and AI determine useful fields automatically.

### Template Mode

Uses a selected company template to extract standardized fields. Missing required fields are automatically created for review.

---

## Processing Pipeline

```
Upload
│
├── Store original file
├── Create processing job
│
▼
Celery Worker
│
├── Parse document
├── Deterministic template-labelled extraction
├── AI extraction (when required)
├── Template enforcement
├── Validation engine
├── AI Review Assistant
│
▼
Human Review
│
├── Accept
├── Correct
├── Add fields
├── Remove custom fields
├── Reject
│
▼
Approved Audit-Ready Record
```

---

## AI Responsibilities

The AI is used to:

- Classify document types
- Extract structured fields
- Assist Free Extraction
- Estimate confidence
- Explain extracted data
- Produce AI Review Assistant summaries
- Highlight potential inconsistencies

The AI **does not**:

- Approve documents
- Reject documents
- Modify approved data automatically
- Override validation rules

---

## Validation

Every extracted field is validated using deterministic rules including:

- Required fields
- Dates
- Email addresses
- Numeric values
- Currency
- Currency codes
- Percentages
- Regex-based validation

Fields below the confidence threshold or failing validation require review.

---

## Review Workspace

The review interface provides:

- Extraction Information
- AI Review Assistant summary
- Original document preview
- Source highlighting
- Confidence indicators
- Validation messages
- Audit timeline
- Original file download

---

## Database

### PostgreSQL

Stores:

- Documents
- Original uploaded files
- Parsed text
- Extracted fields
- Review decisions
- AI review summaries
- Processing jobs
- Audit logs

### Redis

Used only as the Celery message broker.

---

## Background Processing

Celery performs:

- Document processing
- AI extraction
- AI review generation
- Retry of deferred AI jobs
- Recovery of stalled jobs
- Requeueing orphaned pending jobs

Celery Beat schedules automatic recovery tasks.

---

## Technology Stack

| Layer | Tools |
| --- | --- |
| Backend | Python, FastAPI, SQLAlchemy, Celery, uv |
| Frontend | Next.js, React, TypeScript, Tailwind CSS |
| Infrastructure | PostgreSQL, Redis, Docker, Docker Compose |

---

## Sample Templates

**Finance**

- Invoice
- Bank Statement

**Construction**

- Purchase Order
- Progress Claim

Templates define standardized business fields and validation rules while allowing AI to populate missing information where appropriate.

---

## Project Scope

This MVP demonstrates:

- Enterprise document ingestion
- AI-assisted extraction
- Configurable document templates
- Human-in-the-loop review
- Validation
- Auditability
- Asynchronous processing
- Provider-agnostic AI architecture

It is intentionally **not** a reporting platform, chatbot or RAG system.

---

## Future Enhancements

- OCR for scanned documents
- RAG-powered knowledge assistant
- Semantic search
- ERP/CRM integrations
- Authentication and role-based access control
- Template management UI
- Analytics and reporting

---

## Setup, Usage and Reference

### Project layout

```
kyouth-data-ai-project/
├── docker-compose.yml          # frontend, api, worker, beat, postgres, redis
├── backend/app/api/            # REST endpoints
├── backend/app/ai/             # AI providers
├── backend/app/document_templates/
├── backend/app/services/
├── frontend/app/               # pages (upload, review, records)
└── frontend/components/
```

### Prerequisites

- **Docker + Docker Compose** — recommended; no `uv` or `npm` install needed on your machine
- **Manual dev only:** [uv](https://docs.astral.sh/uv/) (backend) and Node.js 22+ (frontend)

`uv sync` is **not required** when using Docker — the backend image runs it during build. You only need `uv sync` if you run the backend locally outside Docker. Same for `npm install` on the frontend.

### Environment

Example files (do not commit real secrets):

- `backend/.env.example` → copy to `backend/.env`
- `frontend/.env.local.example` → copy to `frontend/.env.local` (local frontend dev only)

```bash
cp backend/.env.example backend/.env
```

Set your AI key in `backend/.env` (e.g. `GEMINI_API_KEY`, `AI_PROVIDER=gemini`, `AI_ENABLED=true`). Defaults for `DATABASE_URL` and `REDIS_URL` work with Docker Compose. For local frontend dev: set `NEXT_PUBLIC_API_URL=http://localhost:8000`.

### Run

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs

**Expected input:** upload a supported file (`.txt`, `.md`, `.csv`, `.json`, `.pdf`) or paste `raw_text`; choose `document_type_key` (`auto`, `discovery`, or a template key).

**Expected output:** document is saved with `status: "pending"`, a Celery job is queued, then status moves to `needs_review`, `approved`, `rejected`, or `error`. The review page shows extracted fields, confidence scores, validation messages, and AI review summary.

**Manual dev (optional):** start postgres/redis via compose, then:

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

### Docker networking

```
Browser → http://localhost:3000 (frontend)
       → fetch /api/backend/... 
       → Next.js rewrite (next.config.js)
       → http://api:8000 (backend on compose network)

worker / beat → postgres + redis (same compose network)
```

`docker-compose.yml` sets `API_INTERNAL_URL=http://api:8000` for the frontend. The browser never calls `api:8000` directly; it uses the proxy path `/api/backend`.

### API reference

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/documents` | POST | Upload document |
| `/documents` | GET | List documents (`status`, `q`, `limit` query params) |
| `/documents/{id}` | GET | Document detail + extractions |
| `/documents/{id}/reject` | PATCH | Reject document |
| `/documents/{id}/extractions` | POST | Add field (JSON body) |
| `/extractions/{id}/correct` | PATCH | Correct field (JSON body) |
| `/extractions/{id}/accept` | PATCH | Accept field (JSON body) |
| `/extractions/{id}` | DELETE | Remove custom field |
| `/health` | GET | Health check |
| `/capabilities` | GET | Supported file types |
| `/templates` | GET | List templates |
| `/dashboard/metrics` | GET | Dashboard stats |

**`POST /documents`** (multipart form):

- `file` — uploaded file, **or**
- `raw_text` — pasted text (one of these is required)
- `document_type_key` — `auto` (default), `discovery` (free extraction), or a template key e.g. `invoice_finance`

**Response** (`DocumentOut` JSON): returns immediately with `status: "pending"`, empty `extractions[]`, and a queued `jobs[]` entry. After the worker runs, `GET /documents/{id}` returns populated `extractions[]` and updated `status`.

```json
{
  "id": 1,
  "filename": "invoice.txt",
  "status": "pending",
  "extraction_mode": "auto_detect",
  "parser_type": "raw_text",
  "extractions": [],
  "jobs": [{ "id": 1, "status": "queued", "attempts": 0 }]
}
```

**`PATCH /extractions/{id}/correct`** body: `{ "corrected_value": "...", "field_name": "...", "corrected_by": "demo_user" }`

**`PATCH /extractions/{id}/accept`** body: `{ "accepted_by": "demo_user" }`

### Frontend functions

| File | Functions | Role |
| --- | --- | --- |
| `frontend/app/page.tsx` | `upload()`, `loadDocs()`, `loadCapabilities()`, `loadTemplates()`, `loadMetrics()` | Upload form, document list, dashboard |
| `frontend/app/documents/[id]/page.tsx` | `loadDoc()`, `saveCorrection()`, `acceptField()`, `addMissingField()`, `rejectDocument()`, `removeField()` | Review workspace |
| `frontend/app/records/page.tsx` | `loadRecords()` | Searchable records table |

All use `fetch` against `process.env.NEXT_PUBLIC_API_URL || '/api/backend'`.

### Data and assumptions

**Document statuses** (from `backend/app/models.py`): `pending` → `needs_review` / `approved` / `rejected` / `error`.

**Supported inputs** (from `backend/app/parsers.py`): `.txt`, `.md`, `.csv`, `.json`, `.pdf` with readable text. Scanned PDFs and Office files are not supported.

**AI integration** (from `backend/app/ai/`): provider selected by `AI_PROVIDER` in `.env` (gemini, claude, ollama, mock, openai-compatible). When `AI_ENABLED=true`, the Celery worker calls the provider for field extraction; if AI fails or is rate-limited, deterministic template extraction is used when `AI_FALLBACK_TO_DETERMINISTIC=true`. Fields below `AI_CONFIDENCE_REVIEW_THRESHOLD` (default 0.80) require human review.

**Data flow:**

```
Upload in browser → POST /documents → PostgreSQL + processing_jobs row
→ Celery worker (process_document_job) → parse → extract → validate
→ GET /documents/{id} → reviewer accept/correct/reject → audit_logs
```

No user authentication; all actions use actor `demo_user`. No explicit upload size limit in code.

### Testing

**Backend (curl):**

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/documents \
  -F "raw_text=Invoice #123, Total: RM 500" \
  -F "document_type_key=auto"

curl http://localhost:8000/documents/1
```

**Frontend (manual):**

1. Open http://localhost:3000 and upload a `.txt` or `.pdf` file.
2. Confirm the document appears with `pending`, then changes to `needs_review`.
3. Open the document page, correct a field (`saveCorrection`), accept it (`acceptField`), check the audit timeline.
4. Visit `/records` and confirm the document is searchable.

**Docker communication check:** if the UI loads templates and uploads succeed while `curl http://localhost:8000/health` returns `{"ok": true}`, frontend → `/api/backend` → `api:8000` is working.

### Limitations

- No OCR for scanned PDFs or images (`/capabilities` lists these as deferred)
- No Office formats (docx, xlsx, pptx)
- No user authentication or role-based access
- AI accuracy and speed depend on the configured provider
- Rate limits (`AI_MAX_REQUESTS_PER_MINUTE`, `AI_MAX_REQUESTS_PER_DAY`) may defer jobs back to `pending`
- Chat history is not applicable — documents and audit logs are stored, not conversational sessions
- Rejected documents are view-only and cannot be edited

### Architecture reflection

**Design choices:** Frontend and backend are separate containers so UI and API can be developed and deployed independently. Celery worker and beat handle long-running parsing and AI calls so the API stays responsive. PostgreSQL holds all business state; Redis is only the Celery broker.

**Trade-offs:** Prioritized auditability and human review over full automation. Used Docker Compose for simple local deployment instead of a cloud setup. Kept a lightweight Next.js UI instead of adding auth, template management, or reporting.

**Improvements:** Add OCR, user authentication, template management UI, automated tests, cloud deployment, and stronger monitoring for production use.
