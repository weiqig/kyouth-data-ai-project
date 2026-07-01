'use client';

import { useEffect, useMemo, useState } from 'react';
import { DashboardOverview } from './components/DashboardOverview';
import { DocumentsTable } from './components/DocumentsTable';
import { UploadCard } from './components/UploadCard';
import { fileDisplayName } from '../lib/format';
import type { Capabilities, DashboardMetrics, DocumentRecord, DocumentTemplate } from '../lib/types';

const API = process.env.NEXT_PUBLIC_API_URL || '/api/backend';

export default function Home() {
  const [rawText, setRawText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [templateKey, setTemplateKey] = useState('auto');
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  async function loadDocs() {
    const res = await fetch(`${API}/documents?include_rejected=true`, { cache: 'no-store' });
    if (res.ok) setDocs(await res.json());
  }

  async function loadCapabilities() {
    const res = await fetch(`${API}/capabilities`, { cache: 'no-store' });
    if (res.ok) setCapabilities(await res.json());
  }

  async function loadTemplates() {
    const res = await fetch(`${API}/templates`, { cache: 'no-store' });
    if (res.ok) setTemplates(await res.json());
  }

  async function loadMetrics() {
    const res = await fetch(`${API}/dashboard/metrics`, { cache: 'no-store' });
    if (res.ok) setMetrics(await res.json());
  }

  async function upload() {
    setLoading(true);
    setError(null);
    const form = new FormData();
    if (file) form.append('file', file);
    else form.append('raw_text', rawText);
    form.append('document_type_key', templateKey);

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
    await loadMetrics();
  }

  useEffect(() => {
    loadCapabilities();
    loadTemplates();
    loadDocs();
    loadMetrics();
  }, []);

  const stats = useMemo(() => {
    const needsReview = docs.filter((doc) => doc.status === 'needs_review' || doc.extractions.some((x) => x.needs_review)).length;
    const approved = docs.filter((doc) => doc.status === 'approved').length;
    const pending = docs.filter((doc) => doc.status === 'pending').length;
    const error = docs.filter((doc) => doc.status === 'error').length;
    const rejected = docs.filter((doc) => doc.status === 'rejected').length;
    return { total: docs.length, approved, needsReview, pending, error, rejected };
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
      </section>

      <div className="dashboardGrid">
        <UploadCard
          rawText={rawText}
          file={file}
          capabilities={capabilities}
          templates={templates}
          templateKey={templateKey}
          setTemplateKey={setTemplateKey}
          loading={loading}
          error={error}
          setRawText={setRawText}
          setFile={setFile}
          onUpload={upload}
        />
        <DashboardOverview
          metrics={metrics}
          stats={stats}
          onStatusFilter={setStatusFilter}
          onParserFilter={setQuery}
        />
      </div>

      <DocumentsTable
        docs={filteredDocs}
        query={query}
        statusFilter={statusFilter}
        setQuery={setQuery}
        setStatusFilter={setStatusFilter}
        onRefresh={loadDocs}
      />
    </main>
  );
}
