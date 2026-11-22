import { useTranslations } from "next-intl";

import type { CheckStatus, InvoiceStatus } from "@/lib/invoices";
import { cn } from "@/lib/utils";

const GOOD = "border-emerald-600/30 bg-emerald-600/10 text-emerald-700";
const BAD = "border-destructive/30 bg-destructive/10 text-destructive";
const WARN = "border-amber-500/40 bg-amber-500/10 text-amber-800";
const NEUTRAL = "border-border bg-muted text-muted-foreground";

const INVOICE_STYLES: Record<InvoiceStatus, string> = {
  ready: GOOD,
  approved: GOOD,
  blocked: BAD,
  failed: BAD,
  rejected: NEUTRAL,
  awaiting_extraction: WARN,
  override_requested: WARN,
  received: NEUTRAL,
  processing: NEUTRAL,
};

const CHECK_STYLES: Record<CheckStatus, string> = {
  passed: GOOD,
  failed: BAD,
  warning: WARN,
  skipped: NEUTRAL,
};

const BADGE =
  "inline-flex w-fit items-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap";

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const t = useTranslations("Codes.invoiceStatus");
  return <span className={cn(BADGE, INVOICE_STYLES[status])}>{t(status)}</span>;
}

export function CheckStatusBadge({ status }: { status: CheckStatus }) {
  const t = useTranslations("Codes.checkStatus");
  return <span className={cn(BADGE, CHECK_STYLES[status])}>{t(status)}</span>;
}
