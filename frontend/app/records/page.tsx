'use client';

import { useEffect, useMemo, useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || '/api/backend';
const STATUSES = ['all', 'pending', 'needs_review', 'approved', 'rejected', 'error'];

type ProcessingJob = {
  id: number;
  status: string;
  attempts: number;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

type Extraction = { id: number; field_name: string; needs_review: boolean; accepted: boolean; confidence_score: number; review_confidence_score: number; review_status: string };

type DocumentRecord = {
  id: number;
  filename: string | null;
  content_type: string | null;
  original_file_size?: number | null;
  original_preview_text: string;
  parser_type: string;
  raw_text: string;
  status: string;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
  latest_action_actor?: string | null;
  latest_action?: string | null;
  latest_action_at?: string | null;
  extractions: Extraction[];
  jobs: ProcessingJob[];
};

function statusLabel(value: string) {
  if (value === 'approved') return 'approved';
  return value.replaceAll('_', ' ');
}

function formatDate(value?: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function displayName(doc: DocumentRecord) {
  return doc.filename || `Raw text document #${doc.id}`;
}


export default function RecordsPage() {
  const [records, setRecords] = useState<DocumentRecord[]>([]);
  const [allRecords, setAllRecords] = useState<DocumentRecord[]>([]);
  const [status, setStatus] = useState('all');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => clearTimeout(timer);
  }, [search]);

  async function loadRecords(signal?: AbortSignal) {
    setError(null);
    const params = new URLSearchParams();
    if (status !== 'all') params.set('status', status);
    if (debouncedSearch) params.set('q', debouncedSearch);
    params.set('limit', '200');
    params.set('include_rejected', 'true');

    const totalsParams = new URLSearchParams();
    totalsParams.set('limit', '200');
    totalsParams.set('include_rejected', 'true');

    try {
      const [recordsRes, totalsRes] = await Promise.all([
        fetch(`${API}/documents?${params.toString()}`, { cache: 'no-store', signal }),
        fetch(`${API}/documents?${totalsParams.toString()}`, { cache: 'no-store', signal }),
      ]);
      if (!recordsRes.ok) throw new Error(`Database query failed with ${recordsRes.status}`);
      if (!totalsRes.ok) throw new Error(`Database totals failed with ${totalsRes.status}`);
      setRecords(await recordsRes.json());
      setAllRecords(await totalsRes.json());
      setLastUpdated(new Date());
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError((err as Error).message || 'Failed to load records');
    } finally {
      setLoading(false);
    }
  }


  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    loadRecords(controller.signal);
    return () => controller.abort();
  }, [status, debouncedSearch]);


  const stats = useMemo(() => {
    return allRecords.reduce(
      (acc, doc) => {
        acc.total += 1;
        acc[doc.status] = (acc[doc.status] || 0) + 1;
        return acc;
      },
      { total: 0, pending: 0, needs_review: 0, approved: 0, rejected: 0, error: 0 } as Record<string, number>
    );
  }, [allRecords]);

  return (
    <main>
      <section className="detailHero">
        <div>
          <p className="eyebrow">Database records</p>
          <h1>PostgreSQL Records</h1>
          <p className="heroCopy">
            Search and filter current document records directly from the database. Search and status filters update asynchronously, while the Refresh button gives you a manual fallback.
          </p>
          <a className="backLink" href="/">← Back to upload dashboard</a>
        </div>
        <div className="detailStatus">
          <span className="pulse" />
          <strong>Database view</strong>
          <p className="muted">Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : 'loading...'}</p>
        </div>
      </section>

      <section className="statsGrid compactStats">
        <div className="statCard"><span>Total records</span><strong>{stats.total}</strong></div>
        <div className="statCard"><span>Approved</span><strong>{stats.approved || 0}</strong></div>
        <div className="statCard warning"><span>Needs review</span><strong>{stats.needs_review || 0}</strong></div>
        <div className="statCard danger"><span>Rejected</span><strong>{stats.rejected || 0}</strong></div>
      </section>

      <section className="card">
        <div className="sectionHeader">
          <div>
            <h2>Record filters</h2>
          </div>
          <button className="secondaryButton" onClick={() => loadRecords()} disabled={loading}>{loading ? 'Loading...' : 'Refresh'}</button>
        </div>

        <div className="recordsToolbar">
          <div>
            <label>Search records</label>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search filename, raw text, parser, content type, or error..."
            />
          </div>
        </div>

        <div className="statusChips">
          {STATUSES.map((item) => (
            <button
              key={item}
              className={status === item ? 'chip activeChip' : 'chip'}
              onClick={() => setStatus(item)}
            >
              {statusLabel(item)}
            </button>
          ))}
        </div>

        {error && <p className="error">{error}</p>}
        {!error && loading && records.length === 0 && <p className="emptyState">Loading database records...</p>}
        {!loading && records.length === 0 && <p className="emptyState">No records match the current search/filter.</p>}

        {records.length > 0 && (
          <div className="tableWrap recordsTable">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Document</th>
                  <th>Status</th>
                  <th>Parser</th>
                  <th>Fields</th>
                  <th>Avg review confidence</th>
                  <th>Created at</th>
                  <th>Updated at</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {records.map((doc) => {
                  const avgReviewConfidence = doc.extractions.length
                    ? Math.round((doc.extractions.reduce((sum, item) => sum + item.review_confidence_score, 0) / doc.extractions.length) * 100)
                    : null;
                  return (
                    <tr key={doc.id}>
                      <td>#{doc.id}</td>
                      <td>
                        <strong className="fileNameText">{displayName(doc)}</strong>
                        {doc.error_message && <p className="errorInline compact">{doc.error_message}</p>}
                      </td>
                      <td><span className={`badge status-${doc.status}`}>{statusLabel(doc.status)}</span></td>
                      <td>{doc.parser_type}</td>
                      <td>{doc.extractions.length}</td>
                      <td>{avgReviewConfidence === null ? '—' : `${avgReviewConfidence}%`}</td>
                      <td>{formatDate(doc.created_at)}</td>
                      <td>{formatDate(doc.updated_at || doc.created_at)}</td>
                      <td>
                        <div className="tableActions">
                          <a className="rowAction" href={`/documents/${doc.id}`}>View</a>
                        </div>
                      </td>
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
