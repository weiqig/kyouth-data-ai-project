# Audit-Ready AI Document Processing Pipeline

A one-week MVP full-stack prototype for converting common unstructured and semi-structured documents into reviewable structured records while preserving raw input, extraction provenance, human corrections, durable processing state, and audit history.

## MVP Scope

Supported document types:

- `.txt`
- `.md`
- `.csv`
- `.json`
- basic text-based `.pdf` files with selectable text

Intentionally deferred:

- scanned PDFs and image OCR
- image files such as PNG/JPG/TIFF
- Office files such as DOCX/XLSX/PPTX
- email files and archives
- vector search, advanced auth, and multi-tenant RBAC

## Architecture

PostgreSQL is the source of truth. Redis and Celery are execution infrastructure only.

```text
Next.js frontend
      |
      v
FastAPI API
      |
      v
PostgreSQL: documents + processing_jobs + extractions + corrections + audit_logs
      |
      v
Redis carries only processing_jobs.id
      |
      v
Celery worker reads job/document from PostgreSQL and writes all results back to PostgreSQL
```

Redis does not store business state. Celery tasks receive only a durable `processing_jobs.id`.

Document status is now a business/review state only: `pending`, `needs_review`, `approved`, or `error`. Technical lifecycle events such as `processing_started` and `processing_finished` are kept in `processing_jobs` and `audit_logs` instead of being shown as primary document filters.

Document status is now a business/review state only: `pending`, `needs_review`, `approved`, or `error`. Technical lifecycle events such as `processing_started` and `processing_finished` are kept in `processing_jobs` and `audit_logs` instead of being shown as primary document filters.

## Capabilities

- Upload raw text or files from the MVP type list.
- Parse and normalize text, markdown, CSV, JSON, and selectable-text PDFs.
- Store raw/normalized text in PostgreSQL before processing.
- Create a durable PostgreSQL processing job before Celery is called.
- Process documents asynchronously through Celery.
- Extract prototype fields:
  - document type
  - summary
  - email
  - amount
  - date
  - phone/reference number
  - manual review reason when confidence is low
- Expand structured JSON into queryable extraction rows:
  - JSON arrays create document-level metadata such as `record_count` and `schema_fields`
  - each array item field is stored as `records[index].fieldName`
  - JSON object keys are flattened into dotted extraction field paths
  - structured JSON values receive high confidence because they are copied from validated JSON rather than inferred
- Store confidence score, source snippet, and explanation for each extracted field.
- Mark low-confidence fields as needing review.
- Review extracted fields in the frontend.
- Save human corrections separately without overwriting original extraction output.
- View audit trail events for creation, queueing, processing, completion, and corrections.


## Structured JSON extraction

When a `.json` upload contains an array of records, the extractor no longer reduces the file to only `document_type`, `summary`, and `needs_manual_review_reason`. It now stores document-level metadata plus one extraction row per JSON field.

Example JSON array item:

```json
{
  "raceName": "Kyoto Junior Stakes",
  "grade": "G3",
  "year": "First Year",
  "turn": "11_02",
  "type": "Turf",
  "location": "⇒ Kyoto",
  "length": "Medium",
  "lengthM": "2000 m"
}
```

Stored extraction fields include:

```text
document_type = structured_json_array
record_count = 22
schema_fields = raceName, grade, year, turn, type, location, length, lengthM
records[0].raceName = Kyoto Junior Stakes
records[0].grade = G3
records[0].year = First Year
records[0].turn = 11_02
records[0].type = Turf
records[0].location = ⇒ Kyoto
records[0].length = Medium
records[0].lengthM = 2000 m
```

This keeps structured files useful as searchable, reviewable business records instead of only producing a generic summary.

## Tech Stack

- Frontend: Next.js
- Backend: FastAPI
- Database: PostgreSQL
- Queue broker: Redis
- Worker: Celery
- Python package/runtime management: uv
- Local orchestration: Docker Compose

## Run locally

```bash
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
docker compose up --build
```

Open:

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs

## Important API endpoints

- `GET /health`
- `GET /capabilities`
- `POST /documents`
- `GET /documents`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/audit-logs`
- `PATCH /extractions/{extraction_id}/correct`

## Notes for portfolio presentation

This project is intentionally scoped to be achievable in less than a week while still demonstrating production-oriented engineering:

- database-state-driven workflow
- async worker architecture
- durable job records
- raw-first persistence
- human-in-the-loop review
- immutable AI/prototype output plus separate corrections
- auditability
- Dockerized reproducible local environment
- uv-based Python backend

The deterministic extractor is a stand-in for an LLM call. It already writes the same structure an LLM pipeline would need: field name, value, confidence, source snippet, reasoning, and review flag.

## Frontend visual improvements in this build

This version adds a more dashboard-like frontend while staying within the one-week MVP scope:

- Hero section explaining the database-state-driven architecture.
- KPI cards for total files, approved files, files needing review, and pending files.
- Database-backed "Files from PostgreSQL" table using `GET /documents`.
- Search and status filtering over uploaded files.
- Status badges for document state and latest durable job state.
- Improved document review page with file metadata, extraction counters, job cards, evidence boxes, and a timeline-style audit trail.
- Clear visual distinction for fields that need human review.

The frontend does not store business state locally. The file table is refreshed from the FastAPI backend, and the backend reads document state from PostgreSQL.


## Frontend/API networking note

In Docker Compose, the browser calls the Next.js frontend at `http://localhost:3000`, and the frontend proxies API requests through `/api/backend/*` to the FastAPI service at `http://api:8000` inside the Docker network. This avoids browser `localhost` confusion and CORS/network errors.

For non-Docker frontend development, set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local`.


### uv virtual environment note

The backend image stores the uv-managed virtual environment at `/opt/venv` using `UV_PROJECT_ENVIRONMENT=/opt/venv`. This prevents the `api` and `worker` containers from both trying to create or repair `/app/.venv` inside the bind-mounted backend folder during Docker Compose development.


## Docker startup note

The frontend proxies browser requests through Next.js to the backend service at `http://api:8000` inside Docker. The `frontend` service waits for the FastAPI `/health` endpoint before starting, so `ECONNREFUSED http://api:8000` should not occur during normal startup.

If you previously ran an older build, reset containers and volumes:

```bash
docker compose down -v
docker compose up --build
```

Check backend health directly:

```bash
curl http://localhost:8000/health
```

## Recovering pending jobs

PostgreSQL is the source of truth for work state. If Redis/Celery was down during an upload, old jobs may remain in `processing_jobs` as `queued`, `failed`, or stale `running`.

This prototype now supports three recovery paths:

1. **Automatic worker startup recovery** — every worker boot scans PostgreSQL and requeues recoverable jobs.
2. **Manual API recovery**:

```bash
curl -X POST http://localhost:8000/jobs/requeue-pending
```

3. **Manual CLI recovery**:

```bash
docker compose exec worker uv run python -m app.scripts.requeue_pending_jobs
```

The recovery process only sends `processing_jobs.id` back to Celery. Redis remains a temporary execution queue; document state, retries, audit logs, and results remain in PostgreSQL.

Environment knobs:

```bash
JOB_MAX_ATTEMPTS=3
STALE_JOB_MINUTES=10
```

### Database records page

Open `http://localhost:3000/records` to view current document records from PostgreSQL.

The page supports:

- status filtering: `pending`, `needs_review`, `approved`, `error`
- keyword search against filename, parser type, content type, raw text, and errors
- debounced asynchronous updates
- automatic polling so job state changes appear without refreshing

The frontend calls `GET /documents?status=<status>&q=<search>` so filters are applied by the backend/database, not only by browser state.

## Review confidence handling

The prototype now preserves two separate confidence concepts:

- `confidence_score`: the original prototype/AI extraction confidence. This is never overwritten by user review.
- `review_confidence_score`: the current display/review confidence. Before any review exists, it matches the AI confidence. After a user saves a review or correction, it is recalculated by comparing the original extracted value against the current display value.

Review confidence behavior:

- Exact same reviewed value: `100%`
- Same after case/whitespace normalization: `98%`
- Modified value: similarity score between original AI value and reviewed/display value

Every saved review/correction writes an audit event. If that review changes the document state, for example from `needs_review` to `approved`, the system writes an additional `document_state_changed` audit event.

## Developer database debug page

A read-only developer page is available at:

```text
http://localhost:3000/debug/database
```

It lets you inspect the current PostgreSQL contents for:

- `documents`
- `processing_jobs`
- `extractions`
- `corrections`
- `audit_logs`

The page supports table navigation, text search, row limits, manual refresh, and automatic refresh every 5 seconds. The backend endpoints are intentionally limited to known ORM tables and should be protected or disabled before a real production deployment.

## Approval workflow rule

A document can only become `approved` when all extracted fields satisfy both conditions:

1. `accepted = true`
2. `needs_review = false`

After processing completes, documents move to `needs_review` even if the extractor produced high-confidence fields. The user must explicitly accept each field or save a correction, which also accepts that field. Once the final blocking field is accepted, the backend recalculates the document status and writes a `document_state_changed` audit event.

This keeps `approved` as a true human-reviewed business outcome instead of a technical “worker finished” state.

## Provider-agnostic AI layer

This build adds an optional AI extraction layer while keeping the existing optimized parser strategy.

Extraction order:

```text
Upload
  -> parse/normalize file
  -> choose extraction strategy
      -> structured JSON: deterministic structured extraction
      -> CSV: deterministic extraction/preview
      -> raw text, markdown, selectable-text PDF: optional AI provider
  -> validate normalized extraction fields
  -> write extraction rows to PostgreSQL
  -> human review/acceptance
```

The key optimization is that structured formats are not sent to an LLM by default. JSON and CSV are already machine-readable, so deterministic parsing is cheaper, faster, and more reliable. The AI layer is used where it adds the most value: unstructured or semi-structured text.

The implementation uses OOP and abstract classes:

```text
backend/app/ai/base.py       AIProvider abstract base class and shared result models
backend/app/ai/providers.py  GeminiProvider, AnthropicProvider, OllamaProvider, OpenAICompatibleProvider, MockAIProvider
backend/app/ai/factory.py    AIFactory builds providers from .env configuration
backend/app/ai/service.py    Runtime strategy and AI enablement helpers
backend/app/ai/prompts.py    Shared extraction prompt
```

The worker never lets an AI provider write directly to the database. Providers only return normalized fields. The Celery worker validates those fields and stores them in PostgreSQL using the same audit-ready schema as deterministic extraction.

### Configuring AI

Edit `backend/.env`:

```bash
AI_ENABLED=true
AI_PROVIDER=gemini
AI_APPLY_TO_PARSER_TYPES=raw_text,markdown,pdf_text
AI_FALLBACK_TO_DETERMINISTIC=true
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Supported values for `AI_PROVIDER`:

- `mock` — offline demo provider, no network call
- `gemini` — Google Gemini API
- `anthropic` — Anthropic Claude Messages API
- `ollama` — local Ollama `/api/chat`
- `openai_compatible` — any OpenAI-compatible `/v1/chat/completions` gateway

Recommended default for real AI testing is Gemini because it supports JSON-mode style generation and is straightforward to configure with an API key. Keep `AI_FALLBACK_TO_DETERMINISTIC=true` during development so failed provider calls do not block the document pipeline.

### AI provider behavior

- Gemini uses `GEMINI_API_KEY`, `GEMINI_MODEL`, and `GEMINI_BASE_URL`.
- Anthropic uses `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, and the Messages API.
- Ollama uses `OLLAMA_BASE_URL` and `OLLAMA_MODEL` and can run fully locally if Ollama is available.
- OpenAI-compatible mode allows future providers without changing the worker orchestration.

The AI prompt requires providers to return JSON with:

```json
{
  "fields": [
    {
      "field_name": "invoice_date",
      "value": "2026-06-29",
      "confidence": 0.92,
      "source_snippet": "Invoice date: 2026-06-29",
      "explanation": "The value appears after the Invoice date label."
    }
  ]
}
```

Each field is then stored as an extraction row with confidence, source snippet, explanation, review status, and acceptance state.

## Structured JSON/CSV Review UX

Structured JSON and CSV files are now handled differently from unstructured text/PDF/Markdown:

- Valid JSON/CSV values are copied directly from parsed source data.
- Directly parsed structured fields are auto-accepted by the system.
- The document can become `approved` immediately when all fields are auto-accepted and no validation issue requires review.
- Users can still correct any structured field. Corrections are stored separately and recorded in the audit trail.
- Users can add a missing field from the document review page. Manually added fields are accepted immediately and logged as `field_manually_added`.

This avoids forcing reviewers to accept hundreds of deterministic JSON/CSV fields one by one, while preserving auditability and human correction support.

### Approval audit log

Whenever a document transitions to `approved`, the system now writes a dedicated
`document_approved` audit-log entry. For manual review flows, the actor is the
current reviewer supplied by the frontend/API payload, such as `demo_user`. For
automatically accepted structured JSON/CSV documents, the actor is `system` and
the details explain that approval happened because all structured fields were
accepted deterministically and no fields required review.

### Latest minor UI/review changes

- Extracted field names can now be edited from the document review page.
- Renaming a field is recorded in the audit trail with the current reviewer.
- Saving field changes also accepts that field, preserving the document approval gate.
- The main PostgreSQL files table now shows only the extracted field count, without the extra inline `review` label.
