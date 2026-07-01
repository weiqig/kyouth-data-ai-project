'use client';

import type { DashboardMetrics } from '../../lib/types';
import { actionLabel, formatShortDate, pct, statusLabel } from '../../lib/format';

type Props = {
  metrics: DashboardMetrics | null;
  stats: { total: number; approved: number; needsReview: number; pending: number; error: number; rejected?: number };
  onStatusFilter: (status: string) => void;
  onParserFilter: (parserType: string) => void;
};

export function DashboardOverview({ metrics, stats, onStatusFilter, onParserFilter }: Props) {
  const maxStatusCount = Math.max(...Object.values(metrics?.status_counts || {}), 1);
  const parserCounts = metrics?.parser_counts || [];

  return (
    <section className="card activityCard">
      <div className="sectionHeader">
        <div>
          <h2>Analytics Dashboard</h2>
        </div>
      </div>

      <div className="statusBars">
        {['pending', 'needs_review', 'approved', 'rejected', 'error'].map((status) => {
          const statKey = status === 'needs_review' ? 'needsReview' : status as 'pending' | 'approved' | 'rejected' | 'error';
          const count = metrics?.status_counts?.[status] ?? stats[statKey] ?? 0;
          return (
            <button key={status} className="statusBarButton" onClick={() => onStatusFilter(status)}>
              <span>{statusLabel(status)}</span>
              <strong>{count}</strong>
              <i style={{ width: `${Math.max(6, (count / maxStatusCount) * 100)}%` }} />
            </button>
          );
        })}
      </div>

      <div className="metricMiniGrid">
        <div><span>Fields extracted</span><strong>{metrics?.extraction_metrics.total_fields ?? 0}</strong></div>
        <div><span>Accepted fields</span><strong>{metrics?.extraction_metrics.accepted_fields ?? 0}</strong></div>
        <div><span>Corrections</span><strong>{metrics?.extraction_metrics.corrections ?? 0}</strong></div>
        <div><span>Avg review confidence</span><strong>{pct(metrics?.extraction_metrics.avg_review_confidence ?? 0)}</strong></div>
      </div>

      <div className="activitySplit">
        <div>
          <h3>Recent activity</h3>
          <div className="miniTimeline">
            {(metrics?.recent_activity || []).slice(0, 5).map((item) => (
              <a key={item.id} href={item.document_id ? `/documents/${item.document_id}` : '#'} className="miniTimelineItem">
                <span>{formatShortDate(item.created_at)}</span>
                <strong>{actionLabel(item.action)}</strong>
                <small>{item.filename} • {item.actor}</small>
              </a>
            ))}
            {(!metrics || metrics.recent_activity.length === 0) && <p className="emptyState">No audit activity yet.</p>}
          </div>
        </div>

        <div>
          <div className="inlineSectionHeader">
            <h3>Document types processed</h3>
          </div>
          {parserCounts.length > 0 ? (
            <div className="parserMetricsList">
              {parserCounts.slice(0, 6).map((item) => (
                <button key={item.parser_type} onClick={() => onParserFilter(item.parser_type)}>
                  <div>
                    <strong>{item.parser_type}</strong>
                    <span>{item.count} file{item.count === 1 ? '' : 's'}</span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <p className="emptyState">No parsed files yet.</p>
          )}
        </div>
      </div>

      {metrics && metrics.review_queue.length > 0 && (
        <div className="reviewQueueBox">
          <h3>Review queue</h3>
          {metrics.review_queue.map((item) => (
            <a key={item.id} href={`/documents/${item.id}`}>
              <strong>{item.filename}</strong>
              <span>{item.needs_review_fields} field(s) need attention</span>
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
