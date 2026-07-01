'use client';

type AuditLog = { id: number; action: string; actor: string; details: string; created_at: string };

function formatAuditTime(value?: string | null) {
  if (!value) return { time: '—', date: '' };
  const date = new Date(value);
  return {
    time: new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(date),
    date: new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date),
  };
}

export function AuditTimeline({ logs }: { logs: AuditLog[] }) {
  return (
    <section className="card">
      <h2>Audit trail</h2>
      <div className="auditList">
        {logs.map((log) => {
          const auditTime = formatAuditTime(log.created_at);
          return (
            <div key={log.id} className="auditItem">
              <div className="auditTime">
                <strong>{auditTime.time}</strong>
                <span>{auditTime.date}</span>
              </div>
              <span className="auditDot" />
              <div className="auditContent">
                <strong>{log.action}</strong> <span className="muted">by {log.actor}</span>
                <p>{log.details}</p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
