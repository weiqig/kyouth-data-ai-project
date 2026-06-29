from __future__ import annotations

import json
import re
from dataclasses import dataclass
from sqlalchemy import select, func
from .db import SessionLocal
from .models import AuditLog, Document, DocumentStatus, Extraction, JobStatus, ProcessingJob
from .worker import celery_app
from .ai.service import AISettings, extract_with_configured_ai, should_use_ai


@dataclass
class ExtractedField:
    field_name: str
    value: str
    confidence: float
    snippet: str
    reasoning: str
    auto_accept: bool = False


def _snippet(text: str, value: str, width: int = 120) -> str:
    if not value:
        return text[:width]
    idx = text.lower().find(value.lower())
    if idx < 0:
        return text[:width]
    start = max(0, idx - width // 2)
    end = min(len(text), idx + len(value) + width // 2)
    return text[start:end].strip()


def _classify(text: str, parser_type: str) -> tuple[str, float, str]:
    lower = text.lower()
    if parser_type == 'csv':
        return 'structured_csv', 0.92, 'CSV parser normalized rows and columns before extraction.'
    if parser_type == 'json':
        return 'structured_json', 0.92, 'JSON parser validated and pretty-printed the object before extraction.'
    if parser_type == 'pdf_text':
        return 'text_pdf', 0.86, 'PDF parser extracted selectable text from pages.'
    if any(token in lower for token in ['invoice', 'amount due', 'subtotal', 'tax']):
        return 'invoice_or_receipt', 0.82, 'Financial keywords were detected.'
    if any(token in lower for token in ['contract', 'agreement', 'effective date', 'termination']):
        return 'contract_or_agreement', 0.78, 'Agreement-related keywords were detected.'
    if any(token in lower for token in ['error', 'traceback', 'exception', 'warning']):
        return 'technical_log', 0.76, 'Log/error keywords were detected.'
    return 'general_document', 0.62, 'No strong domain-specific indicators were found.'


def _extract_json_payload(text: str) -> object | None:
    """Return the JSON value embedded in parser-normalized JSON text.

    The parser stores a short human-readable prefix before the pretty-printed
    JSON. This helper finds the first JSON object/array and parses from there.
    """
    starts = [idx for idx in (text.find('['), text.find('{')) if idx >= 0]
    if not starts:
        return None
    start = min(starts)
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


def _flatten_json(value: object, prefix: str = '') -> list[tuple[str, str]]:
    """Flatten nested JSON into dotted field paths for extraction rows."""
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f'{prefix}.{key}' if prefix else str(key)
            rows.extend(_flatten_json(child, child_prefix))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_prefix = f'{prefix}[{idx}]' if prefix else f'records[{idx}]'
            rows.extend(_flatten_json(child, child_prefix))
    else:
        if value is None:
            display = 'null'
        elif isinstance(value, bool):
            display = 'true' if value else 'false'
        else:
            display = str(value)
        rows.append((prefix or 'value', display))
    return rows


def _json_source_snippet(field_name: str, value: str) -> str:
    return f'{field_name}: {value}'[:500]


def _extract_csv_records_payload(text: str) -> list[dict[str, object]] | None:
    marker = 'CSV_JSON_RECORDS:'
    if marker not in text:
        return None
    payload = text.split(marker, 1)[1].strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [row if isinstance(row, dict) else {'value': row} for row in parsed]


def _extract_structured_csv(text: str) -> list[ExtractedField] | None:
    records = _extract_csv_records_payload(text)
    if records is None:
        return None

    schema_keys: list[str] = []
    for row in records:
        for key in row.keys():
            if str(key) not in schema_keys:
                schema_keys.append(str(key))

    summary = (
        f'{len(records)} CSV record(s)'
        + (f' with columns: {", ".join(schema_keys)}.' if schema_keys else '.')
    )
    fields: list[ExtractedField] = [
        ExtractedField('document_type', 'structured_csv', 1.0, text[:220], 'CSV parsed successfully into structured rows.', True),
        ExtractedField('summary', summary, 1.0, summary, 'Summary derived from parsed CSV row and column counts.', True),
        ExtractedField('record_count', str(len(records)), 1.0, f'CSV row count: {len(records)}', 'Counted parsed CSV records.', True),
        ExtractedField('schema_fields', ', '.join(schema_keys), 1.0, ', '.join(schema_keys), 'Collected CSV column headers.', True),
        ExtractedField('primary_entity', 'structured_records', 0.95, text[:160], 'CSV rows represent a collection of structured records.', True),
    ]

    for idx, row in enumerate(records):
        for key, value in row.items():
            field_name = f'records[{idx}].{key}'
            if value is None:
                display = ''
            else:
                display = str(value)
            needs_manual_check = display.strip() == ''
            fields.append(ExtractedField(
                field_name=field_name,
                value=display,
                confidence=0.75 if needs_manual_check else 1.0,
                snippet=f'{field_name}: {display}'[:500],
                reasoning='Directly copied from parsed CSV; no AI inference required.' if not needs_manual_check else 'CSV field was present but empty, so it remains reviewable.',
                auto_accept=not needs_manual_check,
            ))
    return fields


def _extract_structured_json(text: str) -> list[ExtractedField] | None:
    parsed = _extract_json_payload(text)
    if parsed is None:
        return None

    fields: list[ExtractedField] = []
    if isinstance(parsed, list):
        record_count = len(parsed)
        object_items = [item for item in parsed if isinstance(item, dict)]
        schema_keys: list[str] = []
        for item in object_items:
            for key in item.keys():
                if str(key) not in schema_keys:
                    schema_keys.append(str(key))

        document_type = 'structured_json_array'
        summary = (
            f'{record_count} JSON record(s)'
            + (f' with fields: {", ".join(schema_keys)}.' if schema_keys else '.')
        )
        fields.append(ExtractedField('document_type', document_type, 1.0, text[:220], 'Valid JSON array parsed successfully.', True))
        fields.append(ExtractedField('summary', summary, 1.0, summary, 'Summary derived from JSON array length and object keys.', True))
        fields.append(ExtractedField('record_count', str(record_count), 1.0, f'Array length: {record_count}', 'Counted top-level JSON array items.', True))
        if schema_keys:
            fields.append(ExtractedField('schema_fields', ', '.join(schema_keys), 1.0, ', '.join(schema_keys), 'Collected unique keys from JSON object records.', True))
        fields.append(ExtractedField('primary_entity', 'structured_records', 0.95, text[:160], 'Top-level JSON array indicates a collection of structured records.', True))

        for idx, item in enumerate(parsed):
            if isinstance(item, dict):
                for key, value in item.items():
                    for suffix, flattened_value in _flatten_json(value):
                        field_name = f'records[{idx}].{key}' if suffix == str(key) or not suffix else f'records[{idx}].{key}.{suffix}'
                        # For simple values, _flatten_json returns prefix-less when called on scalar; normalize that case.
                        if isinstance(value, (str, int, float, bool)) or value is None:
                            field_name = f'records[{idx}].{key}'
                        fields.append(ExtractedField(
                            field_name=field_name,
                            value=flattened_value,
                            confidence=1.0,
                            snippet=_json_source_snippet(field_name, flattened_value),
                            reasoning='Directly copied from validated JSON; no inference required.',
                            auto_accept=True,
                        ))
            else:
                fields.append(ExtractedField(
                    field_name=f'records[{idx}]',
                    value=json.dumps(item, ensure_ascii=False),
                    confidence=1.0,
                    snippet=_json_source_snippet(f'records[{idx}]', json.dumps(item, ensure_ascii=False)),
                    reasoning='Directly copied top-level JSON array item; no inference required.',
                    auto_accept=True,
                ))
        return fields

    if isinstance(parsed, dict):
        keys = [str(key) for key in parsed.keys()]
        fields.append(ExtractedField('document_type', 'structured_json_object', 1.0, text[:220], 'Valid JSON object parsed successfully.', True))
        fields.append(ExtractedField('summary', f'JSON object with fields: {", ".join(keys)}.', 1.0, ', '.join(keys), 'Summary derived from JSON object keys.', True))
        fields.append(ExtractedField('schema_fields', ', '.join(keys), 1.0, ', '.join(keys), 'Collected keys from the top-level JSON object.', True))
        for field_name, value in _flatten_json(parsed):
            fields.append(ExtractedField(
                field_name=field_name,
                value=value,
                confidence=1.0,
                snippet=_json_source_snippet(field_name, value),
                reasoning='Directly copied from validated JSON; no inference required.',
                auto_accept=True,
            ))
        return fields

    fields.append(ExtractedField('document_type', f'structured_json_{type(parsed).__name__}', 1.0, text[:220], 'Valid scalar JSON parsed successfully.', True))
    fields.append(ExtractedField('value', json.dumps(parsed, ensure_ascii=False), 1.0, text[:220], 'Directly copied JSON scalar value.', True))
    return fields


def deterministic_extract(text: str, parser_type: str) -> list[ExtractedField]:
    """Deterministic MVP extractor.

    This keeps the prototype runnable without paid AI credentials while preserving
    the same storage contract you would use for LLM output: value, confidence,
    source snippet, and explanation/citation. Structured JSON is expanded into
    queryable record-level extraction rows rather than reduced to a summary.
    """
    if parser_type == 'csv':
        structured_csv_fields = _extract_structured_csv(text)
        if structured_csv_fields is not None:
            return structured_csv_fields

    if parser_type == 'json':
        structured_json_fields = _extract_structured_json(text)
        if structured_json_fields is not None:
            return structured_json_fields

    fields: list[ExtractedField] = []

    doc_type, doc_confidence, doc_reason = _classify(text, parser_type)
    fields.append(ExtractedField('document_type', doc_type, doc_confidence, text[:160], doc_reason))

    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = ' '.join(non_empty_lines[:3])[:300] if non_empty_lines else text[:300]
    fields.append(ExtractedField('summary', summary, 0.70 if summary else 0.40, summary[:220], 'Brief extractive summary generated from the first meaningful lines.'))

    email = re.search(r'[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}', text)
    if email:
        value = email.group(0)
        fields.append(ExtractedField('email', value, 0.92, _snippet(text, value), 'Regex matched a valid email-like token.'))

    amount = re.search(r'(?:RM|MYR|USD|EUR|GBP|\$)\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?', text, re.I)
    if amount:
        value = amount.group(0)
        fields.append(ExtractedField('amount', value, 0.84, _snippet(text, value), 'Currency pattern detected in the source text.'))

    date = re.search(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b', text)
    if date:
        value = date.group(0)
        fields.append(ExtractedField('date', value, 0.80, _snippet(text, value), 'Date-like pattern detected.'))

    phone = re.search(r'\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{4}\b', text)
    if phone:
        value = phone.group(0)
        fields.append(ExtractedField('phone_or_reference_number', value, 0.66, _snippet(text, value), 'Number pattern detected; may be a phone, account, or reference number.'))

    if len(fields) <= 2:
        fields.append(ExtractedField('needs_manual_review_reason', 'No high-confidence business fields found.', 0.48, text[:220], 'The document can still be reviewed and corrected by a human.'))

    return fields


def _ai_fields_to_extracted_fields(ai_result) -> list[ExtractedField]:
    return [
        ExtractedField(
            field_name=item.field_name,
            value=item.value,
            confidence=item.confidence,
            snippet=item.source_snippet,
            reasoning=f"AI provider={ai_result.provider}, model={ai_result.model}. {item.explanation}",
        )
        for item in ai_result.fields
    ]


def extract_for_document(text: str, parser_type: str) -> tuple[list[ExtractedField], str]:
    """Choose the lowest-risk extraction strategy for the document.

    Structured JSON is extracted deterministically because it is already
    machine-readable. CSV and other deterministic patterns remain available.
    The configured AI provider is used only for parser types listed in
    AI_APPLY_TO_PARSER_TYPES. If the provider fails and fallback is enabled,
    the worker still completes using deterministic extraction.
    """
    settings = AISettings.from_env()

    # Structured formats should not be sent to an LLM unless explicitly added
    # to AI_APPLY_TO_PARSER_TYPES. This keeps JSON/CSV precise, cheaper, and
    # easier to audit.
    if should_use_ai(parser_type, settings):
        try:
            ai_result = extract_with_configured_ai(document_text=text, parser_type=parser_type)
            fields = _ai_fields_to_extracted_fields(ai_result)
            if fields:
                return fields, f'ai:{ai_result.provider}:{ai_result.model}'
            if not settings.fallback_to_deterministic:
                return [], f'ai:{ai_result.provider}:{ai_result.model}:empty'
        except Exception as exc:  # noqa: BLE001
            if not settings.fallback_to_deterministic:
                raise
            fallback_fields = deterministic_extract(text, parser_type)
            fallback_fields.append(ExtractedField(
                'ai_fallback_reason',
                str(exc),
                0.45,
                str(exc)[:500],
                'Configured AI provider failed, so deterministic fallback was used.',
            ))
            return fallback_fields, f'deterministic_fallback_after_ai_error:{settings.provider}'

    return deterministic_extract(text, parser_type), 'deterministic'


@celery_app.task(name='process_document_job')
def process_document_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
        if not job:
            return
        if job.status not in {JobStatus.QUEUED.value, JobStatus.FAILED.value}:
            return

        doc = db.get(Document, job.document_id)
        if not doc:
            job.status = JobStatus.FAILED.value
            job.error_message = 'Document not found.'
            db.commit()
            return

        job.status = JobStatus.RUNNING.value
        job.attempts += 1
        job.started_at = func.now()
        # Keep document.status as a business/review state. The technical
        # lifecycle is captured by processing_jobs.status and audit_logs.
        db.add(AuditLog(document_id=doc.id, action='processing_started', actor='worker', details=f'Job {job.id} started from PostgreSQL state.'))
        db.commit()

        extracted_fields, extraction_strategy = extract_for_document(doc.raw_text, doc.parser_type)

        db.query(Extraction).filter(Extraction.document_id == doc.id).delete()
        needs_review = False
        auto_accepted_count = 0
        review_required_count = 0
        for item in extracted_fields:
            field_needs_review = item.confidence < 0.75 or not item.auto_accept
            accepted = item.auto_accept and not field_needs_review
            needs_review = needs_review or field_needs_review
            if accepted:
                auto_accepted_count += 1
            else:
                review_required_count += 1
            db.add(Extraction(
                document_id=doc.id,
                field_name=item.field_name,
                extracted_value=item.value,
                confidence_score=item.confidence,
                source_snippet=item.snippet,
                ai_reasoning=item.reasoning,
                needs_review=field_needs_review,
                accepted=accepted,
                accepted_by='system' if accepted else None,
                accepted_at=func.now() if accepted else None,
            ))

        # Structured JSON/CSV fields are copied directly from machine-readable
        # input and are auto-accepted unless validation produced a review flag.
        # AI/unstructured fields remain manually reviewable by default.
        doc.status = DocumentStatus.NEEDS_REVIEW.value if needs_review else DocumentStatus.APPROVED.value
        doc.error_message = None
        job.status = JobStatus.SUCCEEDED.value
        job.finished_at = func.now()
        job.error_message = None
        db.add(AuditLog(document_id=doc.id, action='extraction_strategy_selected', actor='worker', details=f'Extraction strategy: {extraction_strategy}.'))
        db.add(AuditLog(document_id=doc.id, action='structured_fields_auto_accepted', actor='worker', details=f'Auto-accepted {auto_accepted_count} field(s); {review_required_count} field(s) still require review.'))
        db.add(AuditLog(document_id=doc.id, action='processing_finished', actor='worker', details=f'Job {job.id} completed and extraction rows committed. Document status is {doc.status}.'))
        if doc.status == DocumentStatus.APPROVED.value:
            db.add(AuditLog(
                document_id=doc.id,
                action='document_approved',
                actor='system',
                details=(
                    'Document approved automatically by the system because all extracted fields '
                    'were accepted during deterministic structured-data processing and no fields require review.'
                ),
            ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(ProcessingJob, job_id)
        if job:
            doc = db.get(Document, job.document_id)
            job.status = JobStatus.FAILED.value
            job.error_message = str(exc)
            job.finished_at = func.now()
            if doc:
                doc.status = DocumentStatus.ERROR.value
                doc.error_message = str(exc)
                db.add(AuditLog(document_id=doc.id, action='processing_failed', actor='worker', details=str(exc)))
            db.commit()
        raise
    finally:
        db.close()


@celery_app.on_after_finalize.connect
def _register_recovery_on_worker_start(sender, **kwargs):  # noqa: ARG001
    # Declared after task registration so the worker imports app.tasks first.
    pass


from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def recover_jobs_on_worker_start(sender=None, **kwargs):  # noqa: ARG001
    """Automatically restore queued/failed/stale jobs from PostgreSQL on worker boot."""
    from .recovery import enqueue_recoverable_jobs_with_new_session

    result = enqueue_recoverable_jobs_with_new_session()
    print(f"[recovery] worker startup requeued jobs: {result}")
