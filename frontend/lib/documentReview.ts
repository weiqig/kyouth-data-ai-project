import type { Extraction } from './types';

export function confidenceLabel(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function reviewStatusLabel(value: string) {
  return value.replaceAll('_', ' ');
}

export function confidenceTier(value: number) {
  if (value >= 0.9) return { label: 'High', className: 'confidenceHigh' };
  if (value >= 0.8) return { label: 'Medium', className: 'confidenceMedium' };
  return { label: 'Low', className: 'confidenceLow' };
}

export function normalizeSnippet(value?: string | null) {
  return (value || '').trim();
}

export function sourceForExtraction(extraction?: Extraction | null) {
  if (!extraction) return '';
  return normalizeSnippet(extraction.source_snippet) || normalizeSnippet(extraction.display_value) || normalizeSnippet(extraction.extracted_value);
}

function normalizeForSearch(value: string) {
  return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

function findFlexibleIndex(text: string, needle: string) {
  const normalizedNeedle = normalizeForSearch(needle);
  if (!normalizedNeedle) return -1;
  const direct = text.toLowerCase().indexOf(needle.toLowerCase());
  if (direct >= 0) return direct;

  // Loose whitespace fallback: useful when PDF or JSON pretty-printing changes spacing.
  const escaped = needle
    .trim()
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\s+/g, '\\s+');
  try {
    const match = new RegExp(escaped, 'i').exec(text);
    return match?.index ?? -1;
  } catch {
    return -1;
  }
}

export function splitByHighlight(text: string, extraction?: Extraction | null) {
  if (!extraction) return { segments: [{ text, hit: false }], matched: false };

  if (typeof extraction.source_start_char === 'number' && typeof extraction.source_end_char === 'number') {
    const start = Math.max(0, Math.min(text.length, extraction.source_start_char));
    const end = Math.max(start, Math.min(text.length, extraction.source_end_char));
    if (end > start) {
      return {
        matched: true,
        segments: [
          { text: text.slice(0, start), hit: false },
          { text: text.slice(start, end), hit: true },
          { text: text.slice(end), hit: false },
        ],
      };
    }
  }

  const candidates = [
    normalizeSnippet(extraction.source_snippet),
    normalizeSnippet(extraction.display_value),
    normalizeSnippet(extraction.extracted_value),
  ].filter(Boolean);

  for (const candidate of candidates) {
    const index = findFlexibleIndex(text, candidate);
    if (index >= 0) {
      return {
        matched: true,
        segments: [
          { text: text.slice(0, index), hit: false },
          { text: text.slice(index, index + candidate.length), hit: true },
          { text: text.slice(index + candidate.length), hit: false },
        ],
      };
    }
  }
  return { segments: [{ text, hit: false }], matched: false };
}

export function prettyJson(rawText: string) {
  try {
    return JSON.stringify(JSON.parse(rawText), null, 2);
  } catch {
    return rawText;
  }
}

export function csvRows(rawText: string) {
  return rawText
    .trim()
    .split(/\r?\n/)
    .filter(Boolean)
    .slice(0, 51)
    .map((line) => line.split(',').map((cell) => cell.trim()));
}

export function parserLabel(parserType: string) {
  const labels: Record<string, string> = {
    raw_text: 'Text preview',
    markdown: 'Markdown/text preview',
    pdf_text: 'PDF text preview',
    json: 'Pretty JSON preview',
    csv: 'CSV table preview',
  };
  return labels[parserType] || `${parserType} preview`;
}

export function extractAiRunMetadata(extractions: Extraction[]) {
  for (const extraction of extractions) {
    const match = (extraction.ai_reasoning || '').match(/AI provider=([^,]+), model=([^\.]+)\./i);
    if (match) {
      return { provider: match[1].trim(), model: match[2].trim() };
    }
  }
  return null;
}

export function cleanExtractionReason(reasoning: string) {
  return (reasoning || '').replace(/^AI provider=[^,]+, model=[^.]+\.\s*/i, '').trim();
}

export function extractionModeLabel(mode?: string) {
  const labels: Record<string, string> = {
    auto_detect: 'Auto-detect template',
    discovery: 'Free Extraction',
    template: 'Selected template',
  };
  return labels[mode || ''] || (mode ? mode.replaceAll('_', ' ') : 'Unknown');
}
