import Link from "next/link";

import { formatDateTime } from "@/lib/invoices";
import {
  describeEvent,
  type SecurityEvent,
  type Severity,
} from "@/lib/security";
import { cn } from "@/lib/utils";

const SEVERITY: Record<Severity, string> = {
  high: "border-destructive/30 bg-destructive/10 text-destructive",
  medium: "border-amber-500/40 bg-amber-500/10 text-amber-800",
  low: "border-border bg-muted text-muted-foreground",
};

/** The security log for approvers, newest first (read-only). */
export function SecurityEventsTable({ events }: { events: SecurityEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No security events yet.</p>
    );
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th scope="col" className="py-2 font-medium">
            When
          </th>
          <th scope="col" className="py-2 font-medium">
            Severity
          </th>
          <th scope="col" className="py-2 font-medium">
            Event
          </th>
          <th scope="col" className="py-2 font-medium">
            User
          </th>
        </tr>
      </thead>
      <tbody>
        {events.map((event) => (
          <tr key={event.id} className="border-t align-top">
            <td className="py-2 pr-3 whitespace-nowrap">
              <time dateTime={event.at}>{formatDateTime(event.at)}</time>
            </td>
            <td className="py-2 pr-3">
              <span
                className={cn(
                  "inline-flex rounded-md border px-2 py-0.5 text-xs font-medium",
                  SEVERITY[event.severity],
                )}
              >
                {event.severity}
              </span>
            </td>
            <td className="py-2 pr-3 break-words">
              <span className="font-medium">{event.type}</span>
              <p className="text-xs text-muted-foreground">
                {describeEvent(event)}
              </p>
              {event.invoice_id && (
                <Link
                  href={`/invoices/${event.invoice_id}`}
                  className="text-xs underline underline-offset-4"
                >
                  Open invoice
                </Link>
              )}
            </td>
            <td className="py-2 break-all">{event.user_email ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
