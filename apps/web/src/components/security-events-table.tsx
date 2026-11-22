import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { isSecurityEventType } from "@/lib/codes";
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

function Description({ event }: { event: SecurityEvent }) {
  const t = useTranslations("Security.describe");
  const description = describeEvent(event);
  if (description === null) {
    return null;
  }
  return (
    <p className="text-xs text-muted-foreground">
      {t(description.key, description.values)}
    </p>
  );
}

/** The security log for approvers, newest first (read-only). */
export function SecurityEventsTable({ events }: { events: SecurityEvent[] }) {
  const t = useTranslations("Security");
  const codes = useTranslations("Codes");
  const locale = useLocale();
  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("empty")}</p>;
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th scope="col" className="py-2 font-medium">
            {t("when")}
          </th>
          <th scope="col" className="py-2 font-medium">
            {t("severity")}
          </th>
          <th scope="col" className="py-2 font-medium">
            {t("event")}
          </th>
          <th scope="col" className="py-2 font-medium">
            {t("user")}
          </th>
        </tr>
      </thead>
      <tbody>
        {events.map((event) => (
          <tr key={event.id} className="border-t align-top">
            <td className="py-2 pr-3 whitespace-nowrap">
              <time dateTime={event.at}>
                {formatDateTime(event.at, locale)}
              </time>
            </td>
            <td className="py-2 pr-3">
              <span
                className={cn(
                  "inline-flex rounded-md border px-2 py-0.5 text-xs font-medium",
                  SEVERITY[event.severity],
                )}
              >
                {codes(`severity.${event.severity}`)}
              </span>
            </td>
            <td className="py-2 pr-3 break-words">
              <span className="font-medium">
                {isSecurityEventType(event.type)
                  ? codes(`securityEvent.${event.type}`)
                  : event.type}
              </span>
              <Description event={event} />
              {event.invoice_id && (
                <Link
                  href={`/invoices/${event.invoice_id}`}
                  className="text-xs underline underline-offset-4"
                >
                  {t("openInvoice")}
                </Link>
              )}
            </td>
            <td className="py-2 break-all">
              {event.user_email ?? t("noUser")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
