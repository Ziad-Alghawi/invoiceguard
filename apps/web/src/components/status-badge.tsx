import type { CheckStatus, InvoiceStatus } from "@/lib/invoices";
import { cn } from "@/lib/utils";

const GOOD = "border-emerald-600/30 bg-emerald-600/10 text-emerald-700";
const BAD = "border-destructive/30 bg-destructive/10 text-destructive";
const WARN = "border-amber-500/40 bg-amber-500/10 text-amber-800";
const NEUTRAL = "border-border bg-muted text-muted-foreground";

const STYLES: Record<InvoiceStatus | CheckStatus, string> = {
  ready: GOOD,
  approved: GOOD,
  passed: GOOD,
  blocked: BAD,
  failed: BAD,
  rejected: NEUTRAL,
  warning: WARN,
  awaiting_extraction: WARN,
  received: NEUTRAL,
  processing: NEUTRAL,
  skipped: NEUTRAL,
};

export function StatusBadge({
  status,
}: {
  status: InvoiceStatus | CheckStatus;
}) {
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        STYLES[status],
      )}
    >
      {status.replace("_", " ")}
    </span>
  );
}
