import { useLocale, useTranslations } from "next-intl";

import { isAuditAction, isInvoiceStatus } from "@/lib/codes";
import { StatusReason } from "@/components/status-reason";
import { type AuditEvent, auditReason, formatDateTime } from "@/lib/invoices";

/** The invoice's audit log, oldest first. Reasons are what the users wrote. */
export function AuditHistory({ events }: { events: AuditEvent[] }) {
  const t = useTranslations("Audit");
  const codes = useTranslations("Codes");
  const locale = useLocale();
  const status = (value: string) =>
    isInvoiceStatus(value) ? codes(`invoiceStatus.${value}`) : value;
  return (
    <ol className="flex flex-col gap-2 text-sm">
      {events.map((event) => (
        <li key={event.id} className="border-l-2 pl-3">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">
              {isAuditAction(event.action)
                ? codes(`auditAction.${event.action}`)
                : event.action}
            </span>
            {event.status_before && event.status_after && (
              <span className="text-muted-foreground">
                {t("transition", {
                  before: status(event.status_before),
                  after: status(event.status_after),
                })}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground">
            {t.rich("meta", {
              date: formatDateTime(event.at, locale),
              actor: event.actor,
              time: (chunks) => <time dateTime={event.at}>{chunks}</time>,
            })}
          </div>
          {event.reason && (
            <p className="mt-0.5">
              <StatusReason reason={auditReason(event)} />
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
