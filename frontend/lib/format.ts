import type { DocumentRecord } from './types';

export function statusLabel(status: string) {
  return status.replaceAll('_', ' ');
}

export function actionLabel(action: string) {
  return action.replaceAll('_', ' ');
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export function formatShortDate(value: string | null) {
  if (!value) return 'Unknown time';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

export function pct(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function fileDisplayName(doc: DocumentRecord) {
  return doc.filename || `Raw text document #${doc.id}`;
}
