'use client';

import type { Capabilities, DocumentTemplate } from '../../lib/types';

type Props = {
  rawText: string;
  file: File | null;
  capabilities: Capabilities | null;
  templates: DocumentTemplate[];
  templateKey: string;
  setTemplateKey: (value: string) => void;
  loading: boolean;
  error: string | null;
  setRawText: (value: string) => void;
  setFile: (value: File | null) => void;
  onUpload: () => void;
};

export function UploadCard({ rawText, file, capabilities, templates, templateKey, setTemplateKey, loading, error, setRawText, setFile, onUpload }: Props) {
  return (
    <section className="card uploadCard">
      <div className="sectionHeader">
        <div>
          <h2>Upload document</h2>
          <p className="muted">Supported: {capabilities?.supported_extensions.join(', ') || '.txt, .md, .csv, .json, .pdf'}</p>
        </div>
      </div>

      <label>Document template</label>
      <select value={templateKey} onChange={(e) => setTemplateKey(e.target.value)}>
        <option value="auto">Auto-detect template</option>
        <option value="discovery">Free Extraction</option>
        {templates.map((template) => (
          <option key={template.key} value={template.key}>{template.name}</option>
        ))}
      </select>
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
      <button onClick={onUpload} disabled={loading || (!file && !rawText.trim())}>{loading ? 'Uploading...' : 'Upload & Process'}</button>
    </section>
  );
}
