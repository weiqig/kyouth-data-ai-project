'use client';

import { useEffect, useMemo, useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || '/api/backend';

type ProcessingJob = { id: number; status: string; attempts: number };
type Extraction = { id: number; needs_review: boolean };
type Document = {
  id: number;
  filename: string | null;
  content_type: string | null;
  parser_type: string;
  raw_text: string;
  status: string;
  created_at: string;
  updated_at?: string | null;
  extractions: Extraction[];
  jobs: ProcessingJob[];
};

type Capabilities = {
  supported_extensions: string[];
  supported_content_types: string[];
  intentionally_deferred: string[];
};

function statusLabel(status: string) {
  return status.replaceAll('_', ' ');
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function fileDisplayName(doc: Document) {
  return doc.filename || `Raw text document #${doc.id}`;
}

export default function Home() {
  const [rawText, setRawText] = useState('Invoice date: 2026-06-29\nCustomer: demo@example.com\nAmount: RM 1,250.00\nAccount: 1234567890');
  const [file, setFile] = useState<File | null>(null);
  const [docs, setDocs] = useState<Document[]>([]);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [recovering, setRecovering] = useState(false);
  const [recoveryResult, setRecoveryResult] = useState<string | null>(null);

  async function loadDocs() {
    const res = await fetch(`${API}/documents`, { cache: 'no-store' });
    if (res.ok) setDocs(await res.json());
  }

  async function loadCapabilities() {
    const res = await fetch(`${API}/capabilities`, { cache: 'no-store' });
    if (res.ok) setCapabilities(await res.json());
  }

  async function recoverPendingJobs() {
    setRecovering(true);
    setRecoveryResult(null);
    const res = await fetch(`${API}/jobs/requeue-pending`, { method: 'POST' });
    const body = await res.json().catch(() => null);
    if (res.ok && body) {
      setRecoveryResult(`Requeued ${body.total_requeued ?? 0} job(s).`);
      await loadDocs();
    } else {
      setRecoveryResult('Recovery request failed. Check API logs.');
    }
    setRecovering(false);
  }

  async function upload() {
    setLoading(true);
    setError(null);
    const form = new FormData();
    if (file) form.append('file', file);
    else form.append('raw_text', rawText);

    const res = await fetch(`${API}/documents`, { method: 'POST', body: form });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: 'Upload failed' }));
      setError(body.detail || 'Upload failed');
      setLoading(false);
      return;
    }
    setRawText('');
    setFile(null);
    setLoading(false);
    await loadDocs();
  }

  useEffect(() => {
    loadCapabilities();
    loadDocs();
    const timer = setInterval(loadDocs, 2500);
    return () => clearInterval(timer);
  }, []);

  const stats = useMemo(() => {
    const needsReview = docs.filter((doc) => doc.status === 'needs_review' || doc.extractions.some((x) => x.needs_review)).length;
    const approved = docs.filter((doc) => doc.status === 'approved').length;
    const pending = docs.filter((doc) => doc.status === 'pending').length;
    const error = docs.filter((doc) => doc.status === 'error').length;
    return { total: docs.length, approved, needsReview, pending, error };
  }, [docs]);

  const filteredDocs = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return docs.filter((doc) => {
      const matchesStatus = statusFilter === 'all' || doc.status === statusFilter;
      const matchesQuery = !normalized || [fileDisplayName(doc), doc.content_type || '', doc.parser_type, doc.raw_text]
        .join(' ')
        .toLowerCase()
        .includes(normalized);
      return matchesStatus && matchesQuery;
    });
  }, [docs, query, statusFilter]);

  return (
    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">PostgreSQL-state-driven MVP</p>
          <h1>Audit-Ready AI Document Processing Pipeline</h1>
          <p className="heroCopy">Upload supported files, process them through durable database jobs, review extracted fields, and keep a traceable correction history.</p>
        </div>
        <div className="heroPanel">
          <span className="pulse" />
          <strong>Redis/Celery execution only</strong>
          <p>Business state remains in PostgreSQL.</p>
        </div>
      </section>

      <section className="statsGrid">
        <div className="statCard"><span>Total files</span><strong>{stats.total}</strong></div>
        <div className="statCard"><span>Approved</span><strong>{stats.approved}</strong></div>
        <div className="statCard warning"><span>Needs review</span><strong>{stats.needsReview}</strong></div>
        <div className="statCard"><span>Pending</span><strong>{stats.pending}</strong></div>
      </section>

      <div className="dashboardGrid">
        <section className="card uploadCard">
          <div className="sectionHeader">
            <div>
              <h2>Upload document</h2>
              <p className="muted">Supported: {capabilities?.supported_extensions.join(', ') || '.txt, .md, .csv, .json, .pdf'}</p>
            </div>
            <span className="badge">MVP scope</span>
          </div>

          <label>File upload</label>
          <input
            type="file"
            accept=".txt,.md,.csv,.json,.pdf,text/plain,text/markdown,text/csv,application/json,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <p className="muted">Choose a file, or leave it empty and paste raw text below.</p>

          <label>Raw text fallback</label>
          <textarea rows={8} value={rawText} onChange={(e) => setRawText(e.target.value)} disabled={!!file} />

          {error && <p className="error">{error}</p>}
          <button onClick={upload} disabled={loading || (!file && !rawText.trim())}>{loading ? 'Uploading...' : 'Upload & Process'}</button>
        </section>

        <section className="card scopeCard">
          <h2>Pipeline scope</h2>
          <div className="timeline">
            <div><strong>1. Persist</strong><span>Raw file/text saved first</span></div>
            <div><strong>2. Queue</strong><span>PostgreSQL job id sent to Celery</span></div>
            <div><strong>3. Extract</strong><span>Fields, confidence, snippets</span></div>
            <div><strong>4. Review</strong><span>Corrections stored separately</span></div>
          </div>
          <p className="muted">Deferred: {capabilities?.intentionally_deferred.join('; ') || 'scanned PDFs/images/OCR, Office files, email files, archives'}.</p>
        </section>
      </div>

      <section className="card">
        <div className="sectionHeader">
          <div>
            <h2>Files from PostgreSQL</h2>
            <p className="muted">This table is loaded from <code>GET /documents</code>, not local frontend state.</p>
          </div>
          <div className="buttonGroup">
            <button className="secondaryButton" onClick={recoverPendingJobs} disabled={recovering}>{recovering ? 'Recovering...' : 'Recover pending jobs'}</button>
            <button className="secondaryButton" onClick={loadDocs}>Refresh</button>
          </div>
        </div>

        {recoveryResult && <p className="muted">{recoveryResult}</p>}

        <div className="toolbar">
          <input placeholder="Search filename, parser, content, or raw text..." value={query} onChange={(e) => setQuery(e.target.value)} />
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All statuses</option>
            <option value="pending">Pending</option>
            <option value="needs_review">Needs review</option>
            <option value="approved">Approved</option>
            <option value="error">Error</option>
          </select>
        </div>

        {filteredDocs.length === 0 && <p className="emptyState">No matching files found in PostgreSQL.</p>}

        {filteredDocs.length > 0 && (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Status</th>
                  <th>Parser</th>
                  <th>Latest job</th>
                  <th>Fields</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filteredDocs.map((doc) => {
                  const latestJob = doc.jobs?.[doc.jobs.length - 1];
                  return (
                    <tr key={doc.id}>
                      <td>
                        <strong>{fileDisplayName(doc)}</strong>
                        <p className="muted compact">{doc.content_type || 'raw text'} • {doc.raw_text.slice(0, 90)}{doc.raw_text.length > 90 ? '...' : ''}</p>
                      </td>
                      <td><span className={`badge status-${doc.status}`}>{statusLabel(doc.status)}</span></td>
                      <td>{doc.parser_type}</td>
                      <td>{latestJob ? <span className="badge">{latestJob.status}</span> : <span className="muted">none</span>}</td>
                      <td>{doc.extractions.length}</td>
                      <td>{formatDate(doc.created_at)}</td>
                      <td><a className="rowAction" href={`/documents/${doc.id}`}>Review</a></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
