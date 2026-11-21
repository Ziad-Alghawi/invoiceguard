import { useTranslations } from "next-intl";

import { CheckStatusBadge } from "@/components/status-badge";
import { isCheckType } from "@/lib/codes";
import type { InvoiceCheck } from "@/lib/invoices";

/** A check type's label in the UI language; an unknown type as the API sent it. */
export function useCheckTypeLabel(): (type: string) => string {
  const t = useTranslations("Codes.checkType");
  return (type) => (isCheckType(type) ? t(type) : type);
}

/**
 * Check results, worst first (the API's order), with their evidence on demand. The message is
 * the API's text and stays English (ADR-027).
 */
export function CheckList({ checks }: { checks: InvoiceCheck[] }) {
  const t = useTranslations("Checks");
  const checkType = useCheckTypeLabel();
  if (checks.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("none")}</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {checks.map((check) => (
        <li key={check.type} className="rounded-md border p-3 text-sm">
          <div className="flex items-center gap-2">
            <CheckStatusBadge status={check.status} />
            <span className="font-medium">{checkType(check.type)}</span>
          </div>
          <p className="mt-1" lang="en">
            {check.message}
          </p>
          {Object.keys(check.evidence).length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs text-muted-foreground">
                {t("evidence")}
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs">
                {JSON.stringify(check.evidence, null, 2)}
              </pre>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}
