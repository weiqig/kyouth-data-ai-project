'use client';

import { RefObject } from 'react';
import type { DocumentRecord, Extraction } from '../../lib/types';
import { confidenceLabel, confidenceTier, csvRows, parserLabel, prettyJson, sourceForExtraction, splitByHighlight } from '../../lib/documentReview';

type Props = {
  doc: DocumentRecord;
  activeExtraction: Extraction | null;
  activeSourceRef: RefObject<HTMLElement | HTMLTableRowElement | null>;
};

export function DocumentPreview({ doc, activeExtraction, activeSourceRef }: Props) {
  const sourcePreviewText = doc.original_preview_text || doc.raw_text || '';
  const previewText = doc.parser_type === 'json' ? prettyJson(sourcePreviewText) : sourcePreviewText;
  const activeSource = sourceForExtraction(activeExtraction);
  const activeTier = confidenceTier(activeExtraction?.confidence_score || 0);
  const csvPreviewRows = doc.parser_type === 'csv' ? csvRows(previewText) : [];
  const highlightResult = splitByHighlight(previewText, activeExtraction);
  const highlightSegments = highlightResult.segments;
  const canAttemptHighlight = Boolean(activeExtraction && (activeSource || typeof activeExtraction.source_start_char === 'number' || typeof activeExtraction.source_row_index === 'number' || activeExtraction.source_json_path));

  return (
    <section id="document-preview-panel" className="card stickyPanel documentPreviewCard">
      <div className="sectionHeader">
        <div>
          <h2>Document preview</h2>
        </div>
        {activeExtraction && <span className={`confidencePill ${activeTier.className}`}>{activeTier.label} • {confidenceLabel(activeExtraction.confidence_score || 0)}</span>}
      </div>

      {activeExtraction && (
        <div className="activeSourceCard">
          <span>Selected field</span>
          <strong>{activeExtraction.field_name}</strong>
          <p>{activeSource || 'No source snippet was stored for this field.'}</p>
          {activeExtraction.source_line_number && <small>Line {activeExtraction.source_line_number}</small>}
          {activeExtraction.source_json_path && <small>JSON path: {activeExtraction.source_json_path}</small>}
          {activeExtraction.source_row_index !== null && activeExtraction.source_row_index !== undefined && <small>CSV row {activeExtraction.source_row_index}{activeExtraction.source_column_name ? ` • ${activeExtraction.source_column_name}` : ''}</small>}
          {canAttemptHighlight && !highlightResult.matched && doc.parser_type !== 'csv' && <small>Source is recorded, but the exact preview location could not be matched. This can happen when AI snippets are paraphrased or PDF text spacing changes.</small>}
        </div>
      )}

      {doc.parser_type === 'csv' && csvPreviewRows.length > 0 ? (
        <div className="previewTableWrap">
          <table className="previewTable">
            <tbody>
              {csvPreviewRows.map((row, rowIndex) => {
                const normalizedSource = activeSource.toLowerCase();
                const metadataRowHit = activeExtraction?.source_row_index === rowIndex;
                const rowText = row.join(', ').toLowerCase();
                const rowHit = Boolean(metadataRowHit || (normalizedSource && rowText.includes(normalizedSource)));
                return (
                  <tr
                    key={rowIndex}
                    ref={rowHit ? (el) => { activeSourceRef.current = el; } : undefined}
                    className={rowHit ? 'sourceHighlightRow' : ''}
                  >
                    {row.map((cell, cellIndex) => {
                      const columnName = csvPreviewRows[0]?.[cellIndex];
                      const metadataCellHit = rowHit && activeExtraction?.source_column_name && columnName === activeExtraction.source_column_name;
                      const isHit = Boolean(metadataCellHit || (normalizedSource && (cell.toLowerCase().includes(normalizedSource) || rowHit)));
                      return <td className={isHit ? 'sourceHighlightCell' : ''} key={`${rowIndex}-${cellIndex}`}>{cell}</td>;
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <pre className="documentPreviewText" aria-label="Document preview with highlighted source">
          {highlightSegments.map((part, index) => part.hit ? <mark ref={(el) => { activeSourceRef.current = el; }} key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>)}
        </pre>
      )}
    </section>
  );
}
