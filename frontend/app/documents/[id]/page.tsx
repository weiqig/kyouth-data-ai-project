'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import { AuditTimeline } from '../../../components/AuditTimeline';
import { DocumentPreview } from '../../../components/DocumentPreview';
import { formatDate, statusLabel } from '../../../lib/format';
import { cleanExtractionReason, confidenceLabel, confidenceTier, extractionModeLabel, extractAiRunMetadata, reviewStatusLabel, sourceForExtraction } from '../../../lib/documentReview';
import type { DocumentAIReview, DocumentRecord, Extraction } from '../../../lib/types';

const API = process.env.NEXT_PUBLIC_API_URL || '/api/backend';

type AuditLog = { id: number; action: string; actor: string; details: string; created_at: string };

const REJECTION_REASONS = [
  { code: 'incomplete_document', label: 'Incomplete document' },
  { code: 'wrong_document_type', label: 'Wrong document type' },
  { code: 'invalid_template', label: 'Invalid template' },
  { code: 'unsupported_format', label: 'Unsupported or unreadable content' },
  { code: 'duplicate_document', label: 'Duplicate document' },
  { code: 'poor_data_quality', label: 'Poor data quality' },
  { code: 'other', label: 'Other' },
];

function canRemoveExtraction(extraction: Extraction) {
  return extraction.field_name.startsWith('suggested_extra_fields.') || extraction.data_type === 'suggestion' || extraction.ai_reasoning.includes('Manually added by reviewer');
}

function canEditFieldName(extraction: Extraction) {
  // Template fields are canonical schema fields. Lock their names so approved
  // records remain queryable by the client/company's standardized field keys.
  return !extraction.standard_field_key;
}

function fieldDisplayLabel(extraction: Extraction) {
  return extraction.standard_field_key || extraction.field_name;
}

function parseReviewList(value: string) {
  try {
    const parsed = JSON.parse(value || '[]');
    return Array.isArray(parsed) ? parsed.map((item) => String(item)).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function latestAiReview(reviews: DocumentAIReview[] = []) {
  return [...reviews].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0] || null;
}


export default function DocumentPage() {
  const params = useParams<{ id: string }>();
  const documentId = params?.id;

  const [doc, setDoc] = useState<DocumentRecord | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [fieldNameEdits, setFieldNameEdits] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [newFieldName, setNewFieldName] = useState('');
  const [newFieldValue, setNewFieldValue] = useState('');
  const [newFieldSource, setNewFieldSource] = useState('');
  const [addingField, setAddingField] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectionReasonCode, setRejectionReasonCode] = useState('incomplete_document');
  const [rejectionNote, setRejectionNote] = useState('');
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [activeExtractionId, setActiveExtractionId] = useState<number | null>(null);
  const activeSourceRef = useRef<HTMLElement | HTMLTableRowElement | null>(null);

  async function loadDoc() {
    if (!documentId) return;

    const [docRes, auditRes] = await Promise.all([
      fetch(`${API}/documents/${documentId}`, { cache: 'no-store' }),
      fetch(`${API}/documents/${documentId}/audit-logs`, { cache: 'no-store' }),
    ]);
    if (docRes.ok) {
      const nextDoc = await docRes.json();
      setDoc(nextDoc);
      setActiveExtractionId((current) => current ?? nextDoc.extractions?.[0]?.id ?? null);
    }
    if (auditRes.ok) setAuditLogs(await auditRes.json());
  }

  async function saveCorrection(extraction: Extraction) {
    setSavingId(extraction.id);
    const nextValue = edits[extraction.id] ?? extraction.display_value;
    const nextFieldName = canEditFieldName(extraction) ? (fieldNameEdits[extraction.id] ?? extraction.field_name) : extraction.field_name;
    await fetch(`${API}/extractions/${extraction.id}/correct`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        corrected_value: nextValue,
        field_name: canEditFieldName(extraction) ? nextFieldName : undefined,
        corrected_by: 'demo_user',
      }),
    });
    setEdits({ ...edits, [extraction.id]: '' });
    setFieldNameEdits({ ...fieldNameEdits, [extraction.id]: '' });
    setSavingId(null);
    await loadDoc();
  }

  async function acceptField(extractionId: number) {
    setSavingId(extractionId);
    await fetch(`${API}/extractions/${extractionId}/accept`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accepted_by: 'demo_user' }),
    });
    setSavingId(null);
    await loadDoc();
  }

  async function addMissingField() {
    if (!documentId || !newFieldName.trim() || !newFieldValue.trim()) return;
    setAddingField(true);
    await fetch(`${API}/documents/${documentId}/extractions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field_name: newFieldName,
        value: newFieldValue,
        source_snippet: newFieldSource || null,
        added_by: 'demo_user',
      }),
    });
    setNewFieldName('');
    setNewFieldValue('');
    setNewFieldSource('');
    setAddingField(false);
    await loadDoc();
  }

  async function rejectDocument() {
    if (!documentId || !doc || !['pending', 'needs_review'].includes(doc.status)) return;
    const selectedReason = REJECTION_REASONS.find((item) => item.code === rejectionReasonCode)?.label || 'Other';
    const confirmed = window.confirm(`Reject this document?\n\nReason: ${selectedReason}${rejectionNote.trim() ? `\nNote: ${rejectionNote.trim()}` : ''}`);
    if (!confirmed) return;
    setRejecting(true);
    await fetch(`${API}/documents/${documentId}/reject`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rejected_by: 'demo_user', reason_code: rejectionReasonCode, reason: rejectionNote }),
    });
    setRejecting(false);
    await loadDoc();
  }

  async function removeField(extraction: Extraction) {
    if (!canRemoveExtraction(extraction)) return;
    const confirmed = window.confirm(`Remove field "${extraction.field_name}" from this document? This will be logged in the audit trail.`);
    if (!confirmed) return;
    setRemovingId(extraction.id);
    await fetch(`${API}/extractions/${extraction.id}?actor=demo_user`, { method: 'DELETE' });
    setRemovingId(null);
    await loadDoc();
  }

  function selectExtraction(extractionId: number) {
    activeSourceRef.current = null;
    setActiveExtractionId(extractionId);
    document.getElementById('document-preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  useEffect(() => {
    if (!documentId) return;
    loadDoc();
  }, [documentId]);

  useEffect(() => {
    if (!documentId || !doc || doc.status !== 'pending') return;
    const timer = setInterval(loadDoc, 5000);
    return () => clearInterval(timer);
  }, [documentId, doc?.status]);

  const reviewCount = useMemo(() => doc?.extractions.filter((x) => x.needs_review).length || 0, [doc]);
  const unacceptedCount = useMemo(() => doc?.extractions.filter((x) => !x.accepted).length || 0, [doc]);
  const acceptedCount = useMemo(() => doc?.extractions.filter((x) => x.accepted).length || 0, [doc]);
  const templateFields = useMemo(() => doc?.extractions.filter((x) => Boolean(x.standard_field_key)) || [], [doc]);
  const requiredTemplateFields = useMemo(() => templateFields.filter((x) => x.required), [templateFields]);
  const completedRequiredTemplateFields = useMemo(() => requiredTemplateFields.filter((x) => x.accepted && !x.needs_review && x.display_value.trim()).length, [requiredTemplateFields]);
  const suggestedExtraFields = useMemo(() => doc?.extractions.filter((x) => x.field_name.startsWith('suggested_extra_fields.')) || [], [doc]);
  const orderedExtractions = useMemo(() => doc?.extractions || [], [doc]);
  const reviewProgress = useMemo(() => {
    const total = doc?.extractions.length || 0;
    return total ? Math.round((acceptedCount / total) * 100) : 0;
  }, [doc, acceptedCount]);
  const sortedAuditLogs = useMemo(
    () => [...auditLogs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [auditLogs],
  );
  const activeExtraction = useMemo(
    () => orderedExtractions.find((x) => x.id === activeExtractionId) || orderedExtractions[0] || null,
    [orderedExtractions, activeExtractionId],
  );
  const activeSource = sourceForExtraction(activeExtraction);
  const aiRunMetadata = useMemo(() => extractAiRunMetadata(doc?.extractions || []), [doc]);
  const aiReview = useMemo(() => latestAiReview(doc?.ai_reviews || []), [doc]);
  const aiReviewIssues = useMemo(() => parseReviewList(aiReview?.issues_json || '[]'), [aiReview]);
  const aiReviewChecks = useMemo(() => parseReviewList(aiReview?.consistency_checks_json || '[]'), [aiReview]);

  useEffect(() => {
    if (!activeExtractionId) return;
    const timer = window.setTimeout(() => {
      activeSourceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [activeExtractionId, activeSource, doc?.raw_text]);

  if (!doc) return <main><p className="emptyState">Loading document from PostgreSQL...</p></main>;

  const isRejected = doc.status === 'rejected';
  const canReject = doc.status === 'pending' || doc.status === 'needs_review';
  const modeLabel = doc.extraction_mode === 'discovery'
    ? 'Free Extraction — no template'
    : doc.document_type_label
      ? `${doc.extraction_mode === 'auto_detect' ? 'Auto-detected template' : 'Template extraction'} — ${doc.document_type_label}`
      : 'Auto-detect — no matching template, discovery extraction used';

  return (
    <main>
      <p><a className="backLink" href="/">← Back to files</a></p>

      <section className="detailHero">
        <div>
          <p className="eyebrow">Document #{doc.id}</p>
          <h1 className="documentTitle">{doc.filename || `Raw text document #${doc.id}`}</h1>
        </div>
        <div className="detailStatus">
          <span className={`badge status-${doc.status}`}>{statusLabel(doc.status)}</span>
          <a className="secondaryLinkButton" href={`${API}/documents/${doc.id}/download?actor=demo_user`}>Download original</a>
          {canReject && (
            <div className="rejectControls">
              <label>Reject reason</label>
              <select value={rejectionReasonCode} onChange={(event) => setRejectionReasonCode(event.target.value)}>
                {REJECTION_REASONS.map((reason) => <option key={reason.code} value={reason.code}>{reason.label}</option>)}
              </select>
              <input value={rejectionNote} onChange={(event) => setRejectionNote(event.target.value)} placeholder="Optional rejection note" />
              <button className="dangerButton" onClick={rejectDocument} disabled={rejecting}>{rejecting ? 'Rejecting...' : 'Reject document'}</button>
            </div>
          )}
        </div>
      </section>

      {isRejected && <p className="error">This document has been rejected and is now view-only. Rejected records are kept for auditability and can be filtered from the Database Records page.</p>}
      {doc.error_message && <p className="error">{doc.error_message}</p>}

      <section className="reviewSummary card">
        <div>
          <p className="eyebrow">Review workspace</p>
          <h2>{acceptedCount} / {doc.extractions.length} fields accepted</h2>
          <p className="muted compact">Click an extracted field to highlight its source in the original document preview.</p>
          <p className="muted compact">
            Mode: <strong>{modeLabel}</strong>
            {doc.document_type_label && ` • Required fields completed: ${completedRequiredTemplateFields} / ${requiredTemplateFields.length}`}
            {suggestedExtraFields.length > 0 && ` • Suggested extras: ${suggestedExtraFields.length}`}
          </p>
        </div>
        <div className="progressBlock">
          <div className="progressLabel"><strong>{reviewProgress}%</strong><span>review progress</span></div>
          <div className="progressTrack"><i style={{ width: `${reviewProgress}%` }} /></div>
        </div>
      </section>

      <section className="statsGrid compactStats">
        <div className="statCard"><span>{doc.document_type_label ? 'Template fields' : 'Extracted fields'}</span><strong>{doc.document_type_label ? templateFields.length : doc.extractions.length}</strong></div>
        <div className="statCard warning"><span>Needs review</span><strong>{reviewCount}</strong></div>
        <div className="statCard"><span>Awaiting acceptance</span><strong>{unacceptedCount}</strong></div>
        <div className="statCard"><span>{doc.document_type_label ? 'Suggested extras' : 'Audit events'}</span><strong>{doc.document_type_label ? suggestedExtraFields.length : auditLogs.length}</strong></div>
      </section>

      <section className="card extractionInfoCard">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">Extraction information</p>
            <h2>How this document was processed</h2>
          </div>
          <span className="badge">{aiRunMetadata ? 'AI assisted' : 'Parser only'}</span>
        </div>
        <div className="extractionInfoGrid">
          <div><span>Mode</span><strong>{extractionModeLabel(doc.extraction_mode)}</strong></div>
          <div><span>Parser</span><strong>{doc.parser_type.replaceAll('_', ' ')}</strong></div>
          <div><span>Template</span><strong>{doc.document_type_label || 'None'}</strong></div>
          <div><span>AI provider</span><strong>{aiRunMetadata?.provider || 'Not used'}</strong></div>
          {aiRunMetadata && <div><span>AI model</span><strong>{aiRunMetadata.model}</strong></div>}
          <div><span>Fields extracted</span><strong>{doc.extractions.length}</strong></div>
          {doc.document_type_label && <div><span>Required fields</span><strong>{completedRequiredTemplateFields} / {requiredTemplateFields.length}</strong></div>}
          {suggestedExtraFields.length > 0 && <div><span>Suggested extras</span><strong>{suggestedExtraFields.length}</strong></div>}
        </div>
      </section>

      {aiReview && (
        <section className="card aiReviewCard">
          <div className="sectionHeader">
            <div>
              <p className="eyebrow">AI Review Assistant</p>
              <h2>Reviewer briefing</h2>
            </div>
            <span className="badge">{aiReview.provider} / {aiReview.model}</span>
          </div>
          <div className="aiReviewGrid">
            <div>
              <span>Document quality</span>
              <strong>{aiReview.document_quality.replaceAll('_', ' ')}</strong>
            </div>
            <div>
              <span>Overall confidence</span>
              <strong>{confidenceLabel(aiReview.overall_confidence)}</strong>
            </div>
          </div>
          <p>{aiReview.summary}</p>
          {aiReviewIssues.length > 0 && (
            <div className="evidenceBox">
              <strong>Potential issues</strong>
              <ul>{aiReviewIssues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>
            </div>
          )}
          {aiReviewChecks.length > 0 && (
            <div className="evidenceBox">
              <strong>Consistency checks</strong>
              <ul>{aiReviewChecks.map((check, index) => <li key={index}>{check}</li>)}</ul>
            </div>
          )}
          <p className="muted compact"><strong>Recommendation:</strong> {aiReview.review_recommendation}</p>
        </section>
      )}

      <div className="reviewWorkspaceGrid">
        <DocumentPreview doc={doc} activeExtraction={activeExtraction} activeSourceRef={activeSourceRef} />

        <section className="card">
          <h2>Extracted fields</h2>
          {doc.document_type_label && <p className="muted compact">Template fields are listed in the configured template order. Suggested and manually added fields appear after official schema fields.</p>}
          {!doc.document_type_label && <p className="muted compact">Discovery fields follow the extracted/source order where available.</p>}
          {isRejected && <p className="emptyState">View-only mode: rejected documents cannot be edited, accepted, corrected, or extended with missing fields.</p>}
          {!isRejected && (doc.parser_type === 'json' || doc.parser_type === 'csv') && (
            <p className="emptyState">Structured JSON/CSV fields are copied directly from the source and auto-accepted by default. Use corrections when a value must be changed, or add a missing field below.</p>
          )}
          {doc.extractions.length === 0 && <p className="emptyState">Waiting for the Celery worker to process the PostgreSQL job.</p>}
          {orderedExtractions.map((x) => {
            const tier = confidenceTier(x.confidence_score);
            const isActive = x.id === activeExtraction?.id;
            return (
              <div key={x.id} className={`extractionCard ${x.needs_review ? 'review' : ''} ${isActive ? 'activeExtractionCard' : ''}`}>
                <div className="sectionHeader">
                  <button className="fieldSelectButton" type="button" onClick={() => selectExtraction(x.id)}>
                    <strong>{canEditFieldName(x) ? (fieldNameEdits[x.id] || x.field_name) : fieldDisplayLabel(x)}</strong>
                    <span>Show source</span>
                  </button>
                  <div className="fieldBadges">
                    <span className={`confidencePill ${tier.className}`}>{tier.label} • {confidenceLabel(x.confidence_score)}</span>
                    {x.standard_field_key ? <span className="badge">template field</span> : x.field_name.startsWith('suggested_extra_fields.') ? <span className="badge">suggestion</span> : null}
                    {x.validation_status && <span className={`badge validation-${x.validation_status}`}>validation: {x.validation_status.replaceAll('_', ' ')}</span>}
                    {x.accepted ? <span className="badge status-approved">accepted</span> : x.needs_review ? <span className="badge reviewBadge">needs review</span> : <span className="badge reviewBadge">awaiting acceptance</span>}
                  </div>
                </div>

                <p className="muted compact">
                  Review confidence {confidenceLabel(x.review_confidence_score)} • {reviewStatusLabel(x.review_status)}
                  {x.standard_field_key ? ` • Standard key: ${x.standard_field_key}` : ''}
                  {x.required ? ' • Required' : ''}
                  {x.validation_message ? ` • Validation: ${x.validation_message}` : ''}
                </p>

                <label>{canEditFieldName(x) ? 'Field name' : 'Template field key'}</label>
                <input
                  value={canEditFieldName(x) ? (fieldNameEdits[x.id] ?? x.field_name) : fieldDisplayLabel(x)}
                  onChange={(e) => setFieldNameEdits({ ...fieldNameEdits, [x.id]: e.target.value })}
                  readOnly={isRejected || !canEditFieldName(x)}
                />
                {!canEditFieldName(x) && <p className="muted compact">Template field names are locked to keep approved records queryable by the standardized schema. Edit the value instead.</p>}

                <label>Original prototype/AI value</label>
                <input value={x.extracted_value} readOnly />

                <label>Review/display value</label>
                <input value={edits[x.id] ?? x.display_value} onChange={(e) => setEdits({ ...edits, [x.id]: e.target.value })} readOnly={isRejected} />

                <div className="confidenceGrid">
                  <div>
                    <span>Original AI confidence</span>
                    <strong>{confidenceLabel(x.confidence_score)}</strong>
                  </div>
                  <div>
                    <span>Review/display confidence</span>
                    <strong>{confidenceLabel(x.review_confidence_score)}</strong>
                  </div>
                  <div>
                    <span>Review status</span>
                    <strong>{reviewStatusLabel(x.review_status)}</strong>
                  </div>
                  <div>
                    <span>Validation</span>
                    <strong>{x.validation_status ? x.validation_status.replaceAll('_', ' ') : 'not checked'}</strong>
                  </div>
                  <div>
                    <span>Accepted</span>
                    <strong>{x.accepted ? `Yes${x.accepted_by ? ` by ${x.accepted_by}` : ''}` : 'No'}</strong>
                  </div>
                </div>

                <details className="sourceDetails" open={isActive}>
                  <summary>Source and extraction explanation</summary>
                  <div className="evidenceBox">
                    <p><strong>Source snippet:</strong> {x.source_snippet || 'No source snippet stored.'}</p>
                    <p><strong>Reason:</strong> {cleanExtractionReason(x.ai_reasoning) || 'No explanation stored.'}</p>
                    {x.standard_field_key && <p><strong>Standard field key:</strong> {x.standard_field_key} {x.data_type ? `(${x.data_type})` : ''}</p>}
                    {x.validation_message && <p><strong>Validation:</strong> {x.validation_message} {x.validation_rule ? `(rule: ${x.validation_rule})` : ''}</p>}
                    <p><strong>Approval rule:</strong> The document becomes approved only when every extracted field is accepted and no field still needs review.</p>
                  </div>
                </details>

                <div className="buttonRow">
                  <button onClick={() => acceptField(x.id)} disabled={isRejected || x.accepted || savingId === x.id}>{savingId === x.id ? 'Saving...' : 'Accept field'}</button>
                  <button
                    onClick={() => saveCorrection(x)}
                    disabled={
                      isRejected ||
                      savingId === x.id ||
                      !((edits[x.id] && edits[x.id] !== x.display_value) || (canEditFieldName(x) && fieldNameEdits[x.id] && fieldNameEdits[x.id] !== x.field_name))
                    }
                  >
                    {savingId === x.id ? 'Saving...' : (canEditFieldName(x) ? 'Save field & accept' : 'Save value & accept')}
                  </button>
                  {canRemoveExtraction(x) && (
                    <button className="secondaryDangerButton" onClick={() => removeField(x)} disabled={isRejected || removingId === x.id}>
                      {removingId === x.id ? 'Removing...' : 'Remove field'}
                    </button>
                  )}
                </div>

                {x.corrections.length > 0 && (
                  <details>
                    <summary>Correction / review history</summary>
                    {x.corrections.map((c) => (
                      <p key={c.id}>{c.corrected_by}: {c.old_value} → {c.corrected_value} <span className="muted">({formatDate(c.corrected_at)})</span></p>
                    ))}
                  </details>
                )}
              </div>
            );
          })}

          {!isRejected && <div className="addFieldBox">
            <h3>Add missing field</h3>
            <p className="muted compact">Use this when the original document contains an important value that was not included in the extracted fields. Manually added fields are accepted immediately and recorded in the audit trail.</p>
            <label>Field name</label>
            <input value={newFieldName} onChange={(e) => setNewFieldName(e.target.value)} placeholder="e.g. invoice_number or records[0].customField" />
            <label>Value</label>
            <input value={newFieldValue} onChange={(e) => setNewFieldValue(e.target.value)} placeholder="Enter the missing value" />
            <label>Source snippet / note optional</label>
            <input value={newFieldSource} onChange={(e) => setNewFieldSource(e.target.value)} placeholder="Where this value came from, or why it was added" />
            <button onClick={addMissingField} disabled={addingField || !newFieldName.trim() || !newFieldValue.trim()}>{addingField ? 'Adding...' : 'Add missing field'}</button>
          </div>}
        </section>
      </div>

      <AuditTimeline logs={sortedAuditLogs} />
    </main>
  );
}
