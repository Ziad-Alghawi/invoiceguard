import { type AuditEvent, formatDateTime } from "@/lib/invoices";

/** The invoice's audit log, oldest first. */
export function AuditHistory({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="flex flex-col gap-2 text-sm">
      {events.map((event) => (
        <li key={event.id} className="border-l-2 pl-3">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">{event.action}</span>
            {event.status_before && event.status_after && (
              <span className="text-muted-foreground">
                {event.status_before} → {event.status_after}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground">
            <time dateTime={event.at}>{formatDateTime(event.at)}</time> ·{" "}
            {event.actor}
          </div>
          {event.reason && <p className="mt-0.5">{event.reason}</p>}
        </li>
      ))}
    </ol>
  );
}
