'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL || '/api/backend';

type Correction = { id: number; old_value: string; corrected_value: string; corrected_by: string; corrected_at: string };
type Extraction = {
  id: number;
  field_name: string;
  extracted_value: string;
  display_value: string;
  confidence_score: number;
  review_confidence_score: number;
  review_status: string;
  source_snippet: string;
  ai_reasoning: string;
  needs_review: boolean;
  accepted: boolean;
  accepted_by?: string | null;
  accepted_at?: string | null;
  corrections: Correction[];
};
type ProcessingJob = { id: number; status: string; attempts: number; error_message?: string | null; created_at?: string; started_at?: string | null; finished_at?: string | null };
type AuditLog = { id: number; action: string; actor: string; details: string; created_at: string };
type Document = {
  id: number;
  filename: string | null;
  content_type: string | null;
  parser_type: string;
  raw_text: string;
  status: string;
  error_message?: string | null;
  created_at: string;
  extractions: Extraction[];
  jobs: ProcessingJob[];
};

function formatDate(value?: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function formatAuditTime(value?: string | null) {
  if (!value) return { time: '—', date: '' };
  const date = new Date(value);
  return {
    time: new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(date),
    date: new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date),
  };
}

function statusLabel(status: string) {
  return status.replaceAll('_', ' ');
}

function confidenceLabel(value: number) {
  return `${Math.round(value * 100)}%`;
}

function reviewStatusLabel(value: string) {
  return value.replaceAll('_', ' ');
}

export default function DocumentPage() {
  const params = useParams<{ id: string }>();
  const documentId = params?.id;

  const [doc, setDoc] = useState<Document | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [fieldNameEdits, setFieldNameEdits] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [newFieldName, setNewFieldName] = useState('');
  const [newFieldValue, setNewFieldValue] = useState('');
  const [newFieldSource, setNewFieldSource] = useState('');
  const [addingField, setAddingField] = useState(false);

  async function loadDoc() {
    if (!documentId) return;

    const [docRes, auditRes] = await Promise.all([
      fetch(`${API}/documents/${documentId}`, { cache: 'no-store' }),
      fetch(`${API}/documents/${documentId}/audit-logs`, { cache: 'no-store' }),
    ]);
    if (docRes.ok) setDoc(await docRes.json());
    if (auditRes.ok) setAuditLogs(await auditRes.json());
  }

  async function saveCorrection(extraction: Extraction) {
    setSavingId(extraction.id);
    const nextValue = edits[extraction.id] ?? extraction.display_value;
    const nextFieldName = fieldNameEdits[extraction.id] ?? extraction.field_name;
    await fetch(`${API}/extractions/${extraction.id}/correct`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        corrected_value: nextValue,
        field_name: nextFieldName,
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

  useEffect(() => {
    if (!documentId) return;

    loadDoc();
    const timer = setInterval(loadDoc, 2500);
    return () => clearInterval(timer);
  }, [documentId]);

  const reviewCount = useMemo(() => doc?.extractions.filter((x) => x.needs_review).length || 0, [doc]);
  const unacceptedCount = useMemo(() => doc?.extractions.filter((x) => !x.accepted).length || 0, [doc]);
  const sortedAuditLogs = useMemo(
    () => [...auditLogs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [auditLogs],
  );

  if (!doc) return <main><p className="emptyState">Loading document from PostgreSQL...</p></main>;

  return (
    <main>
      <p><a className="backLink" href="/">← Back to files</a></p>

      <section className="detailHero">
        <div>
          <p className="eyebrow">Document #{doc.id}</p>
          <h1>{doc.filename || `Raw text document #${doc.id}`}</h1>
          <p className="muted">{doc.content_type || 'raw text'} • parser: {doc.parser_type} • uploaded {formatDate(doc.created_at)}</p>
        </div>
        <div className="detailStatus">
          <span className={`badge status-${doc.status}`}>{statusLabel(doc.status)}</span>
          {reviewCount > 0 && <span className="badge reviewBadge">{reviewCount} field(s) need review</span>}
          {unacceptedCount > 0 && <span className="badge reviewBadge">{unacceptedCount} awaiting acceptance</span>}
        </div>
      </section>

      {doc.error_message && <p className="error">{doc.error_message}</p>}

      <section className="statsGrid compactStats">
        <div className="statCard"><span>Extracted fields</span><strong>{doc.extractions.length}</strong></div>
        <div className="statCard warning"><span>Needs review</span><strong>{reviewCount}</strong></div>
        <div className="statCard"><span>Awaiting acceptance</span><strong>{unacceptedCount}</strong></div>
        <div className="statCard"><span>Jobs</span><strong>{doc.jobs.length}</strong></div>
        <div className="statCard"><span>Audit events</span><strong>{auditLogs.length}</strong></div>
      </section>

      <section className="card">
        <h2>Durable PostgreSQL jobs</h2>
        <div className="jobList">
          {doc.jobs.map((job) => (
            <div className="jobItem" key={job.id}>
              <strong>Job #{job.id}</strong>
              <span className="badge">{job.status}</span>
              <span className="muted">attempts {job.attempts}</span>
              {job.error_message && <span className="errorInline">{job.error_message}</span>}
            </div>
          ))}
        </div>
      </section>

      <div className="grid">
        <section className="card stickyPanel">
          <h2>Original / normalized text</h2>
          <p className="muted">This is the raw normalized content stored in PostgreSQL before processing.</p>
          <pre>{doc.raw_text}</pre>
        </section>

        <section className="card">
          <h2>Extracted fields</h2>
          {(doc.parser_type === 'json' || doc.parser_type === 'csv') && (
            <p className="emptyState">Structured JSON/CSV fields are copied directly from the source and auto-accepted by default. Use corrections when a value must be changed, or add a missing field below.</p>
          )}
          {doc.extractions.length === 0 && <p className="emptyState">Waiting for the Celery worker to process the PostgreSQL job.</p>}
          {doc.extractions.map((x) => (
            <div key={x.id} className={`extractionCard ${x.needs_review ? 'review' : ''}`}>
              <div className="sectionHeader">
                <div>
                  <strong>{fieldNameEdits[x.id] || x.field_name}</strong>
                  <p className="muted compact">AI confidence {confidenceLabel(x.confidence_score)}</p>
                  <p className="muted compact">Review confidence {confidenceLabel(x.review_confidence_score)} • {reviewStatusLabel(x.review_status)}</p>
                </div>
                {x.accepted ? <span className="badge status-approved">accepted</span> : x.needs_review ? <span className="badge reviewBadge">needs review</span> : <span className="badge reviewBadge">awaiting acceptance</span>}
              </div>

              <label>Field name</label>
              <input value={fieldNameEdits[x.id] ?? x.field_name} onChange={(e) => setFieldNameEdits({ ...fieldNameEdits, [x.id]: e.target.value })} />

              <label>Original prototype/AI value</label>
              <input value={x.extracted_value} readOnly />

              <label>Review/display value</label>
              <input value={edits[x.id] ?? x.display_value} onChange={(e) => setEdits({ ...edits, [x.id]: e.target.value })} />

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
                  <span>Accepted</span>
                  <strong>{x.accepted ? `Yes${x.accepted_by ? ` by ${x.accepted_by}` : ''}` : 'No'}</strong>
                </div>
              </div>

              <div className="evidenceBox">
                <p><strong>Source snippet:</strong> {x.source_snippet}</p>
                <p><strong>Reason:</strong> {x.ai_reasoning}</p>
                <p><strong>Confidence handling:</strong> AI confidence is preserved. Review confidence is recalculated after a saved review by comparing the original AI value with the current display value.</p>
                <p><strong>Approval rule:</strong> The document becomes approved only when every extracted field is accepted and no field still needs review.</p>
              </div>

              <div className="buttonRow">
                <button onClick={() => acceptField(x.id)} disabled={x.accepted || savingId === x.id}>{savingId === x.id ? 'Saving...' : 'Accept field'}</button>
                <button
                  onClick={() => saveCorrection(x)}
                  disabled={
                    savingId === x.id ||
                    !((edits[x.id] && edits[x.id] !== x.display_value) || (fieldNameEdits[x.id] && fieldNameEdits[x.id] !== x.field_name))
                  }
                >
                  {savingId === x.id ? 'Saving...' : 'Save field changes & accept'}
                </button>
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
          ))}

          <div className="addFieldBox">
            <h3>Add missing field</h3>
            <p className="muted compact">Use this when the original document contains an important value that was not included in the extracted fields. Manually added fields are accepted immediately and recorded in the audit trail.</p>
            <label>Field name</label>
            <input value={newFieldName} onChange={(e) => setNewFieldName(e.target.value)} placeholder="e.g. invoice_number or records[0].customField" />
            <label>Value</label>
            <input value={newFieldValue} onChange={(e) => setNewFieldValue(e.target.value)} placeholder="Enter the missing value" />
            <label>Source snippet / note optional</label>
            <input value={newFieldSource} onChange={(e) => setNewFieldSource(e.target.value)} placeholder="Where this value came from, or why it was added" />
            <button onClick={addMissingField} disabled={addingField || !newFieldName.trim() || !newFieldValue.trim()}>{addingField ? 'Adding...' : 'Add missing field'}</button>
          </div>
        </section>
      </div>

      <section className="card">
        <h2>Audit trail</h2>
        <div className="auditList">
          {sortedAuditLogs.map((log) => {
            const auditTime = formatAuditTime(log.created_at);
            return (
              <div key={log.id} className="auditItem">
                <div className="auditTime">
                  <strong>{auditTime.time}</strong>
                  <span>{auditTime.date}</span>
                </div>
                <span className="auditDot" />
                <div className="auditContent">
                  <strong>{log.action}</strong> <span className="muted">by {log.actor}</span>
                  <p>{log.details}</p>
                  <span className="muted compact">{formatDate(log.created_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
}
