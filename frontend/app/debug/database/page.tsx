'use client';

import { useEffect, useMemo, useState } from 'react';

const API = '/api/backend';

type DebugTable = {
  name: string;
  columns: string[];
};

type DebugRows = {
  table: string;
  columns: string[];
  rows: Record<string, unknown>[];
  limit: number;
  offset: number;
};

const friendlyTableName: Record<string, string> = {
  documents: 'Documents',
  processing_jobs: 'Processing Jobs',
  extractions: 'Extractions',
  corrections: 'Corrections',
  audit_logs: 'Audit Logs',
  document_ai_reviews: 'AI Review Assistant',
};

function formatCell(value: unknown) {
  if (value === null || value === undefined || value === '') return <span className="muted">—</span>;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  const text = String(value);
  if (text.length > 180) return `${text.slice(0, 180)}…`;
  return text;
}

export default function DatabaseDebugPage() {
  const [tables, setTables] = useState<DebugTable[]>([]);
  const [activeTable, setActiveTable] = useState('documents');
  const [rows, setRows] = useState<DebugRows | null>(null);
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [limit, setLimit] = useState(100);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<string>('');

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 350);
    return () => clearTimeout(timer);
  }, [query]);

  async function loadTables() {
    const res = await fetch(`${API}/debug/tables`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to load debug tables');
    const data = await res.json();
    setTables(data);
    if (data?.[0]?.name && !activeTable) setActiveTable(data[0].name);
  }

  async function loadRows() {
    if (!activeTable) return;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (debouncedQuery.trim()) params.set('q', debouncedQuery.trim());
      params.set('limit', String(limit));
      const res = await fetch(`${API}/debug/tables/${activeTable}?${params.toString()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`Failed to load ${activeTable}`);
      setRows(await res.json());
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load table rows');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTables().catch((err) => setError(err instanceof Error ? err.message : 'Failed to load debug tables'));
  }, []);

  useEffect(() => {
    loadRows();
  }, [activeTable, debouncedQuery, limit]);

  const columns = useMemo(() => rows?.columns ?? tables.find((table) => table.name === activeTable)?.columns ?? [], [rows, tables, activeTable]);

  return (
    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">Developer Debug</p>
          <h1>Database Tables</h1>
          <p className="heroCopy">
            Inspect the current PostgreSQL records behind the prototype. This page is read-only and intended for local development/debugging.
          </p>
        </div>
        <div className="heroPanel">
          <strong><span className="pulse" />Live read-only view</strong>
          <p>Auto-refreshes every 5 seconds. Last updated: {lastUpdated || 'not loaded yet'}.</p>
        </div>
      </section>

      <section className="card">
        <div className="sectionHeader">
          <div>
            <h2>Tables</h2>
          </div>
          <button className="secondaryButton" onClick={loadRows} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh now'}</button>
        </div>

        <div className="statusChips">
          {tables.map((table) => (
            <button
              key={table.name}
              className={`chip ${activeTable === table.name ? 'activeChip' : ''}`}
              onClick={() => setActiveTable(table.name)}
            >
              {friendlyTableName[table.name] ?? table.name}
            </button>
          ))}
        </div>

        <div className="recordsToolbar">
          <label>
            Search current table
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search text columns in this table..."
            />
          </label>
          <label>
            Row limit
            <select value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
              <option value={25}>25 rows</option>
              <option value={50}>50 rows</option>
              <option value={100}>100 rows</option>
              <option value={250}>250 rows</option>
              <option value={500}>500 rows</option>
            </select>
          </label>
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      <section className="card">
        <div className="sectionHeader">
          <div>
            <h2>{friendlyTableName[activeTable] ?? activeTable}</h2>
            <p className="muted compact">{rows?.rows.length ?? 0} visible rows from <code>{activeTable}</code>.</p>
          </div>
          {loading && <span className="badge status-running">Loading</span>}
        </div>

        {!rows?.rows.length ? (
          <div className="emptyState">No rows found for the current table/search.</div>
        ) : (
          <div className="tableWrap debugTableWrap">
            <table className="recordsTable debugTable">
              <thead>
                <tr>
                  {columns.map((column) => <th key={column}>{column}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.rows.map((row, index) => (
                  <tr key={`${activeTable}-${row.id ?? index}`}>
                    {columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
