'use client';

import type { DocumentRecord } from '../../lib/types';
import { fileDisplayName, formatDate, statusLabel } from '../../lib/format';

type Props = {
  docs: DocumentRecord[];
  query: string;
  statusFilter: string;
  setQuery: (value: string) => void;
  setStatusFilter: (value: string) => void;
  onRefresh: () => void;
};

export function DocumentsTable({ docs, query, statusFilter, setQuery, setStatusFilter, onRefresh }: Props) {
  return (
    <section className="card">
      <div className="sectionHeader">
        <div>
          <h2>Processed files</h2>
        </div>
        <div className="buttonGroup">
          <button className="secondaryButton" onClick={onRefresh}>Refresh</button>
        </div>
      </div>


      <div className="toolbar">
        <input placeholder="Search filename, parser, content, or raw text..." value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All</option>
          <option value="pending">Pending</option>
          <option value="needs_review">Needs review</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="error">Error</option>
        </select>
      </div>

      {docs.length === 0 && <p className="emptyState">No matching files found.</p>}

      {docs.length > 0 && (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Template</th>
                <th>Parser</th>
                <th>Action</th>
                <th>Fields</th>
                <th>Created at</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => {
                const latestActor = doc.latest_action_actor || 'system';
                const latestAction = doc.latest_action ? doc.latest_action.replaceAll('_', ' ') : 'created';
                return (
                  <tr key={doc.id}>
                    <td>
                      <strong className="fileNameText">{fileDisplayName(doc)}</strong>
                      <p className="muted compact">{doc.content_type || 'raw text'} • {doc.document_type_label ? `${doc.document_type_label} • ` : ''}{doc.raw_text.slice(0, 90)}{doc.raw_text.length > 90 ? '...' : ''}</p>
                    </td>
                    <td><span className={`badge status-${doc.status}`}>{statusLabel(doc.status)}</span></td>
                    <td>{doc.extraction_mode === 'discovery' ? <span className="muted">Discovery</span> : doc.document_type_label || <span className="muted">Auto-detect</span>}</td>
                    <td>{doc.parser_type}</td>
                    <td><span className="muted compact"><strong>{latestActor}</strong></span></td>
                    <td>{doc.extractions.length}</td>
                    <td>{formatDate(doc.created_at)}</td>
                    <td><a className="rowAction" href={`/documents/${doc.id}`}>{doc.status === 'approved' ? 'View' : 'Review'}</a></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
