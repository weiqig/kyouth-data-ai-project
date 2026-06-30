from __future__ import annotations

import json
import re
from dataclasses import dataclass
from sqlalchemy import select, func
from celery.exceptions import Retry
from .db import SessionLocal
from .models import AuditLog, Document, DocumentAIReview, DocumentStatus, Extraction, FieldDefinition, JobStatus, ProcessingJob
from .worker import celery_app
from .ai.service import AISettings, should_use_ai, should_use_ai_review_assistant
from .ai.factory import AIFactory
from .review_policy import confidence_review_threshold, requires_confidence_review
from .services.template_service import apply_template_to_fields, infer_template_key, get_template_definition, template_prompt_contract
from .services.template_extraction_service import extract_template_labelled_fields, required_field_keys
from .services.validation_service import validate_value
from .ai.controls import (
    AIRateLimitExceeded,
    ai_cache_key,
    load_cached_ai_result,
    reserve_ai_request_quota,
    save_ai_result_to_cache,
    sha256_text,
    utcnow,
)


@dataclass
class ExtractedField:
    field_name: str
    value: str
    confidence: float
    snippet: str
    reasoning: str
    auto_accept: bool = False
    standard_field_key: str | None = None
    template_key: str | None = None
    data_type: str | None = None
    required: bool = False
    validation: dict | None = None
    source_line_number: int | None = None
    source_start_char: int | None = None
    source_end_char: int | None = None
    source_json_path: str | None = None
    source_row_index: int | None = None
    source_column_name: str | None = None


def _source_span(text: str, value: str) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    idx = text.lower().find(value.lower())
    if idx < 0:
        return None, None
    return idx, idx + len(value)


def _line_number_for_offset(text: str, offset: int | None) -> int | None:
    if offset is None or offset < 0:
        return None
    return text.count('\n', 0, offset) + 1


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
                source_row_index=idx + 1,
                source_column_name=str(key),
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
                            source_json_path=field_name,
                        ))
            else:
                fields.append(ExtractedField(
                    field_name=f'records[{idx}]',
                    value=json.dumps(item, ensure_ascii=False),
                    confidence=1.0,
                    snippet=_json_source_snippet(f'records[{idx}]', json.dumps(item, ensure_ascii=False)),
                    reasoning='Directly copied top-level JSON array item; no inference required.',
                    auto_accept=True,
                    source_json_path=f'records[{idx}]',
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
                source_json_path=field_name,
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


def extract_for_document(text: str, parser_type: str, db=None, template_key: str | None = None) -> tuple[list[ExtractedField], str, str | None]:
    """Choose the lowest-risk extraction strategy for the document.

    Structured JSON/CSV is deterministic. For template mode, an additional
    deterministic labelled-field pass runs before AI so obvious business fields
    such as `PO Number: PO-7788` are captured using template labels/aliases. AI
    remains available to fill ambiguous gaps, with DB-backed cache/idempotency
    and provider request throttling. If provider quota is exhausted,
    AIRateLimitExceeded is raised so the job can stay pending and retry later
    instead of failing.
    """
    settings = AISettings.from_env()

    template_labelled_fields, labelled_template = extract_template_labelled_fields(
        text, template_key, field_factory=ExtractedField
    )
    if template_labelled_fields and labelled_template:
        found_required = {item.standard_field_key for item in template_labelled_fields if item.required and item.value.strip()}
        required_keys = required_field_keys(labelled_template)
        # Clean labelled documents can be processed without an AI request. This
        # fixes template-mode samples where the template is detected correctly but
        # generic extraction misses obvious key-value lines.
        if required_keys and required_keys.issubset(found_required):
            fields, template, missing = apply_template_to_fields(template_labelled_fields, template_key, field_factory=ExtractedField)
            suffix = f':template:{template.key}' if template else ''
            return fields, f'deterministic_labelled{suffix}', template.key if template else None

    if should_use_ai(parser_type, settings):
        provider = AIFactory.create()
        template_contract = template_prompt_contract(template_key)
        ai_document_text = f"{template_contract}\n\nDocument content:\n{text}" if template_contract else text
        # Include template mode in the cache dimensions. The same document can be
        # processed against different client schemas, so template-specific AI
        # output must not be reused across incompatible templates.
        effective_parser_type = f"{parser_type}:template:{template_key}" if template_key else parser_type
        content_hash = sha256_text(text)
        cache_key = ai_cache_key(
            content_hash=content_hash,
            parser_type=effective_parser_type,
            provider=provider.provider_name,
            model=provider.model,
        )

        if db is not None:
            cached = load_cached_ai_result(db, cache_key=cache_key)
            if cached and cached.fields:
                
                fields = [*template_labelled_fields, *_ai_fields_to_extracted_fields(cached)]
                fields, template, missing = apply_template_to_fields(fields, template_key, field_factory=ExtractedField)
                suffix = f':template:{template.key}' if template else ''
                return fields, f'ai_cache:{cached.provider}:{cached.model}{suffix}', template.key if template else None

        try:
            if db is not None:
                reserve_ai_request_quota(db, provider=provider.provider_name, model=provider.model)
                # Persist quota reservation before making the external request so
                # parallel workers share one PostgreSQL-backed counter.
                db.commit()

            ai_result = provider.extract_fields(document_text=ai_document_text, parser_type=effective_parser_type)
            if db is not None and ai_result.fields:
                save_ai_result_to_cache(
                    db,
                    cache_key=cache_key,
                    content_hash=content_hash,
                    parser_type=effective_parser_type,
                    result=ai_result,
                )
            fields = [*template_labelled_fields, *_ai_fields_to_extracted_fields(ai_result)]
            if fields:
                
                fields, template, missing = apply_template_to_fields(fields, template_key, field_factory=ExtractedField)
                suffix = f':template:{template.key}' if template else ''
                return fields, f'ai:{ai_result.provider}:{ai_result.model}{suffix}', template.key if template else None
            if not settings.fallback_to_deterministic:
                return [], f'ai:{ai_result.provider}:{ai_result.model}:empty', template_key
        except AIRateLimitExceeded as exc:
            if settings.defer_on_rate_limit:
                raise
            if not settings.fallback_to_deterministic:
                raise
            fallback_fields = [*template_labelled_fields, *deterministic_extract(text, parser_type)]
            fallback_fields.append(ExtractedField(
                'ai_fallback_reason',
                str(exc),
                0.45,
                str(exc)[:500],
                'AI provider quota was exhausted, so deterministic fallback was used because AI_DEFER_ON_RATE_LIMIT=false.',
            ))
            
            fallback_fields, template, missing = apply_template_to_fields(fallback_fields, template_key, field_factory=ExtractedField)
            return fallback_fields, f'deterministic_fallback_after_ai_rate_limit:{settings.provider}', template.key if template else None
        except Exception as exc:  # noqa: BLE001
            if not settings.fallback_to_deterministic:
                raise
            fallback_fields = [*template_labelled_fields, *deterministic_extract(text, parser_type)]
            fallback_fields.append(ExtractedField(
                'ai_fallback_reason',
                str(exc),
                0.45,
                str(exc)[:500],
                'Configured AI provider failed, so deterministic fallback was used.',
            ))
            
            fallback_fields, template, missing = apply_template_to_fields(fallback_fields, template_key, field_factory=ExtractedField)
            return fallback_fields, f'deterministic_fallback_after_ai_error:{settings.provider}', template.key if template else None

    
    fields = [*template_labelled_fields, *deterministic_extract(text, parser_type)]
    fields, template, missing = apply_template_to_fields(fields, template_key, field_factory=ExtractedField)
    suffix = f':template:{template.key}' if template else ''
    strategy = 'deterministic_labelled' if template_labelled_fields else 'deterministic'
    return fields, f'{strategy}{suffix}', template.key if template else None


def _build_ai_review_context(doc: Document, fields: list[ExtractedField], extraction_strategy: str) -> str:
    template_label = doc.document_type_label or doc.document_type_key or "None"
    field_lines = []
    for item in fields[:80]:
        field_lines.append(
            json.dumps(
                {
                    "field_name": item.field_name,
                    "standard_field_key": item.standard_field_key,
                    "value": item.value,
                    "confidence": item.confidence,
                    "required": item.required,
                    "data_type": item.data_type,
                    "validation": item.validation or {},
                },
                ensure_ascii=False,
            )
        )
    return f"""Document id: {doc.id}
Filename: {doc.filename}
Parser: {doc.parser_type}
Extraction mode: {doc.extraction_mode}
Template: {template_label}
Extraction strategy: {extraction_strategy}

Original parsed document text:
{doc.raw_text[:6000]}

Extracted/template fields:
""" + "\n".join(field_lines)


def _create_ai_review_if_enabled(db, doc: Document, fields: list[ExtractedField], extraction_strategy: str, settings: AISettings) -> bool:
    if not should_use_ai_review_assistant(settings):
        return False
    provider = AIFactory.create()
    reserve_ai_request_quota(db, provider=provider.provider_name, model=provider.model)
    db.commit()
    context = _build_ai_review_context(doc, fields, extraction_strategy)
    result = provider.review_document(review_context=context)
    db.query(DocumentAIReview).filter(DocumentAIReview.document_id == doc.id).delete()
    db.add(DocumentAIReview(
        document_id=doc.id,
        provider=result.provider,
        model=result.model,
        summary=result.summary,
        overall_confidence=result.overall_confidence,
        document_quality=result.document_quality,
        review_recommendation=result.review_recommendation,
        issues_json=json.dumps(result.issues, ensure_ascii=False),
        consistency_checks_json=json.dumps(result.consistency_checks, ensure_ascii=False),
    ))
    db.add(AuditLog(
        document_id=doc.id,
        action='ai_review_assistant_completed',
        actor='worker',
        details=f'AI Review Assistant generated reviewer briefing using {result.provider}/{result.model}.',
    ))
    return True


def _create_deterministic_ai_review(db, doc: Document, fields: list[ExtractedField], extraction_strategy: str, reason: str = "LLM review not used") -> bool:
    """Create a non-LLM reviewer briefing so every processed document has a review card.

    The UI always shows an AI Review Assistant section. When the provider is
    disabled, rate-limited, or unavailable, this deterministic fallback uses the
    same validation/template signals that drive the review workflow. It never
    changes extracted values or approval rules.
    """
    missing_required = [
        item.field_name
        for item in fields
        if item.required and not (item.value or "").strip()
    ]
    validation_failures = [
        f"{item.field_name}: {item.validation.get('message', 'Validation failed')}"
        for item in fields
        if item.validation and item.validation.get('status') == 'invalid'
    ]
    low_confidence = [
        item.field_name
        for item in fields
        if requires_confidence_review(item.confidence)
    ]

    issues: list[str] = []
    if missing_required:
        issues.append("Missing required fields: " + ", ".join(missing_required[:12]))
    if validation_failures:
        issues.extend(validation_failures[:12])
    if low_confidence:
        issues.append("Low-confidence fields require review: " + ", ".join(low_confidence[:12]))

    if not fields:
        issues.append("No extracted fields were produced for this document.")

    checks: list[str] = []
    if doc.document_type_label or doc.document_type_key:
        checks.append(f"Template context applied: {doc.document_type_label or doc.document_type_key}.")
    else:
        checks.append("No template was enforced; fields were produced using Free Extraction or parser-based discovery.")
    if not missing_required:
        checks.append("No required template fields are currently missing.")
    if not validation_failures:
        checks.append("No validation failures were detected by deterministic rules.")

    avg_confidence = round(sum(item.confidence for item in fields) / len(fields), 3) if fields else 0.0
    document_quality = "needs_review" if issues else "good"
    if validation_failures or len(missing_required) >= 3:
        document_quality = "poor"

    if issues:
        recommendation = "Review the listed issues before approving this document."
    else:
        recommendation = "No significant deterministic issues were detected. Review and approve if the extracted values match the source document."

    summary = (
        f"Deterministic reviewer briefing generated for {doc.filename or 'this document'}. "
        f"Extraction strategy: {extraction_strategy}. {reason}."
    )

    db.query(DocumentAIReview).filter(DocumentAIReview.document_id == doc.id).delete()
    db.add(DocumentAIReview(
        document_id=doc.id,
        provider="system",
        model="deterministic-review",
        summary=summary,
        overall_confidence=avg_confidence,
        document_quality=document_quality,
        review_recommendation=recommendation,
        issues_json=json.dumps(issues, ensure_ascii=False),
        consistency_checks_json=json.dumps(checks, ensure_ascii=False),
    ))
    db.add(AuditLog(
        document_id=doc.id,
        action='ai_review_assistant_fallback_created',
        actor='worker',
        details=f'Deterministic AI Review Assistant fallback created. Reason: {reason}',
    ))
    return True


@celery_app.task(name='process_document_job', bind=True, max_retries=None)
def process_document_job(self, job_id: int) -> None:
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

        if doc.status == DocumentStatus.REJECTED.value:
            job.status = JobStatus.FAILED.value
            job.error_message = 'Document was rejected before processing; worker skipped it.'
            job.finished_at = func.now()
            db.add(AuditLog(
                document_id=doc.id,
                action='processing_skipped_rejected_document',
                actor='worker',
                details=f'Job {job.id} skipped because document #{doc.id} is rejected.',
            ))
            db.commit()
            return

        job.status = JobStatus.RUNNING.value
        job.attempts += 1
        job.started_at = func.now()
        # Keep document.status as a business/review state. The technical
        # lifecycle is captured by processing_jobs.status and audit_logs.
        db.add(AuditLog(document_id=doc.id, action='processing_started', actor='worker', details=f'Job {job.id} started from PostgreSQL state.'))
        db.commit()

        try:
            # Extraction modes are intentionally distinct:
            # - discovery: never infer/apply a template; freely extract fields from raw content.
            # - auto_detect: infer a matching template when possible, otherwise fall back to free discovery.
            # - template: enforce the user-selected template contract.
            if doc.extraction_mode == 'discovery':
                selected_template_key = None
            elif doc.document_type_key:
                selected_template_key = doc.document_type_key
            else:
                selected_template_key = infer_template_key(doc.raw_text, doc.parser_type)

            extracted_fields, extraction_strategy, applied_template_key = extract_for_document(doc.raw_text, doc.parser_type, db=db, template_key=selected_template_key)
            if applied_template_key:
                template = get_template_definition(applied_template_key)
                doc.document_type_key = applied_template_key
                doc.document_type_label = template.name if template else applied_template_key
                if doc.extraction_mode != 'template':
                    doc.extraction_mode = 'auto_detect'
            elif doc.extraction_mode != 'template':
                doc.document_type_key = None
                doc.document_type_label = None
        except AIRateLimitExceeded as exc:
            # Keep durable PostgreSQL state pending/queued. The Celery message is
            # retried after the provider window resets; recovery can also requeue it.
            job.status = JobStatus.QUEUED.value
            job.attempts = max(0, job.attempts - 1)
            job.error_message = None
            job.deferred_reason = str(exc)
            job.next_retry_at = exc.reset_at
            doc.status = DocumentStatus.PENDING.value
            doc.error_message = None
            db.add(AuditLog(
                document_id=doc.id,
                action='ai_rate_limited_job_deferred',
                actor='worker',
                details=(
                    f'Job {job.id} kept pending because {exc.provider}/{exc.model} '
                    f'reached its {exc.window_type} quota of {exc.limit}. '
                    f'Next retry after {exc.reset_at.isoformat()}.'
                ),
            ))
            db.commit()
            raise self.retry(countdown=exc.reset_after_seconds) from exc

        db.refresh(doc)
        if doc.status == DocumentStatus.REJECTED.value:
            job.status = JobStatus.FAILED.value
            job.error_message = 'Document was rejected while processing; extraction write was skipped.'
            job.finished_at = func.now()
            db.add(AuditLog(
                document_id=doc.id,
                action='processing_write_skipped_rejected_document',
                actor='worker',
                details=f'Job {job.id} completed extraction work but skipped database writes because document #{doc.id} was rejected.',
            ))
            db.commit()
            return

        db.query(Extraction).filter(Extraction.document_id == doc.id).delete()
        needs_review = False
        auto_accepted_count = 0
        review_required_count = 0
        threshold = confidence_review_threshold()
        definition_ids: dict[tuple[str, str], int] = {}
        if doc.document_type_key:
            for definition in db.scalars(select(FieldDefinition).where(FieldDefinition.field_key.in_([item.standard_field_key for item in extracted_fields if item.standard_field_key]))).all():
                definition_ids[(doc.document_type_key, definition.field_key)] = definition.id
        for item in extracted_fields:
            # Any field below the configured confidence threshold requires review,
            # even if the original value and display value are currently identical.
            validation_result = validate_value(
                field_name=item.standard_field_key or item.field_name,
                value=item.value,
                data_type=item.data_type,
                required=item.required,
                validation=item.validation or {},
            )
            field_needs_review = validation_result.requires_review or requires_confidence_review(item.confidence) or not item.auto_accept
            accepted = item.auto_accept and not field_needs_review
            needs_review = needs_review or field_needs_review
            if accepted:
                auto_accepted_count += 1
            else:
                review_required_count += 1
            db.add(Extraction(
                document_id=doc.id,
                field_name=item.field_name,
                field_definition_id=definition_ids.get((item.template_key or doc.document_type_key or '', item.standard_field_key or '')),
                template_key=item.template_key or doc.document_type_key,
                standard_field_key=item.standard_field_key,
                data_type=item.data_type,
                required=item.required,
                validation_status=validation_result.status,
                validation_message=validation_result.message,
                validation_rule=validation_result.rule,
                extracted_value=item.value,
                confidence_score=item.confidence,
                source_snippet=item.snippet,
                source_line_number=item.source_line_number,
                source_start_char=item.source_start_char,
                source_end_char=item.source_end_char,
                source_json_path=item.source_json_path,
                source_row_index=item.source_row_index,
                source_column_name=item.source_column_name,
                ai_reasoning=item.reasoning,
                needs_review=field_needs_review,
                accepted=accepted,
                accepted_by='system' if accepted else None,
                accepted_at=utcnow() if accepted else None,
            ))

        # AI Review Assistant: every processed document gets a review briefing.
        # The preferred path uses the configured LLM provider. If that is disabled,
        # skipped, rate-limited, or fails non-fatally, a deterministic fallback
        # review is created from template/validation/confidence signals so the
        # review page remains consistent for every document.
        ai_review_created = False
        ai_review_fallback_reason = "AI Review Assistant provider was disabled or skipped"
        try:
            ai_review_created = _create_ai_review_if_enabled(db, doc, extracted_fields, extraction_strategy, AISettings.from_env())
        except AIRateLimitExceeded as exc:
            settings = AISettings.from_env()
            if settings.review_assistant_required:
                raise
            ai_review_fallback_reason = f"provider quota was reached: {exc}"
            db.add(AuditLog(
                document_id=doc.id,
                action='ai_review_assistant_deferred_or_skipped',
                actor='worker',
                details=f'AI Review Assistant provider skipped because quota was reached: {exc}',
            ))
        except Exception as exc:  # noqa: BLE001
            settings = AISettings.from_env()
            if settings.review_assistant_required:
                raise
            ai_review_fallback_reason = f"provider failed non-fatally: {exc}"
            db.add(AuditLog(
                document_id=doc.id,
                action='ai_review_assistant_skipped',
                actor='worker',
                details=f'AI Review Assistant provider failed non-fatally: {exc}',
            ))

        if not ai_review_created:
            ai_review_created = _create_deterministic_ai_review(db, doc, extracted_fields, extraction_strategy, ai_review_fallback_reason)

        # Structured JSON/CSV fields are copied directly from machine-readable
        # input and are auto-accepted unless validation produced a review flag.
        # AI/unstructured fields remain manually reviewable by default.
        doc.status = DocumentStatus.NEEDS_REVIEW.value if needs_review else DocumentStatus.APPROVED.value
        doc.error_message = None
        job.status = JobStatus.SUCCEEDED.value
        job.finished_at = func.now()
        job.error_message = None
        job.deferred_reason = None
        job.next_retry_at = None
        db.add(AuditLog(document_id=doc.id, action='extraction_strategy_selected', actor='worker', details=f'Extraction strategy: {extraction_strategy}.'))
        db.add(AuditLog(document_id=doc.id, action='structured_fields_auto_accepted', actor='worker', details=f'Auto-accepted {auto_accepted_count} field(s); {review_required_count} field(s) still require review. Confidence threshold: {round(threshold * 100)}%. Validation rules were applied to extracted/template fields. AI Review Assistant: {'created' if ai_review_created else 'not created'}.'))
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
    except Retry:
        raise
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


def _dispatch_recovered_jobs(job_ids: list[int]) -> int:
    dispatched = 0
    for recovered_job_id in job_ids:
        process_document_job.delay(recovered_job_id)
        dispatched += 1
    return dispatched


@celery_app.task(name="retry_deferred_jobs")
def retry_deferred_jobs() -> dict[str, int]:
    """Retry AI-deferred jobs whose quota window has elapsed."""
    from .services.job_recovery_service import collect_deferred_jobs_ready_for_retry

    db = SessionLocal()
    try:
        plan = collect_deferred_jobs_ready_for_retry(db)
        return {"deferred_requeued": _dispatch_recovered_jobs(plan.job_ids)}
    finally:
        db.close()


@celery_app.task(name="recover_stuck_processing_jobs")
def recover_stuck_processing_jobs() -> dict[str, int]:
    """Recover jobs left in running state after worker crashes."""
    from .services.job_recovery_service import collect_stuck_processing_jobs

    db = SessionLocal()
    try:
        plan = collect_stuck_processing_jobs(db)
        return {"stuck_requeued": _dispatch_recovered_jobs(plan.job_ids)}
    finally:
        db.close()


@celery_app.task(name="requeue_orphaned_pending_jobs")
def requeue_orphaned_pending_jobs() -> dict[str, int]:
    """Recreate Celery messages for durable queued jobs stored in PostgreSQL."""
    from .services.job_recovery_service import collect_orphaned_pending_jobs

    db = SessionLocal()
    try:
        plan = collect_orphaned_pending_jobs(db)
        return {"pending_requeued": _dispatch_recovered_jobs(plan.job_ids)}
    finally:
        db.close()


@celery_app.task(name="retry_failed_jobs")
def retry_failed_jobs() -> dict[str, int]:
    """Retry failed jobs that still have attempts remaining."""
    from .services.job_recovery_service import collect_retryable_failed_jobs

    db = SessionLocal()
    try:
        plan = collect_retryable_failed_jobs(db)
        return {"failed_requeued": _dispatch_recovered_jobs(plan.job_ids)}
    finally:
        db.close()


@celery_app.task(name="run_job_recovery")
def run_job_recovery() -> dict[str, int]:
    """Run the full Celery-owned job recovery workflow."""
    results = {
        "deferred_requeued": retry_deferred_jobs.run()["deferred_requeued"],
        "stuck_requeued": recover_stuck_processing_jobs.run()["stuck_requeued"],
        "pending_requeued": requeue_orphaned_pending_jobs.run()["pending_requeued"],
        "failed_requeued": retry_failed_jobs.run()["failed_requeued"],
    }
    results["total_requeued"] = sum(results.values())
    return results


from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def recover_jobs_on_worker_start(sender=None, **kwargs):  # noqa: ARG001
    """Kick off recovery on worker boot without putting maintenance in the API."""
    try:
        run_job_recovery.delay()
    except Exception as exc:  # noqa: BLE001
        print(f"[recovery] startup recovery task could not be scheduled: {exc}")
