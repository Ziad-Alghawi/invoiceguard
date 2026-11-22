import { useTranslations } from "next-intl";

import { useCheckTypeLabel } from "@/components/check-list";
import { isReasonCode } from "@/lib/codes";
import type { Reason } from "@/lib/invoices";

/**
 * A status reason in the UI language when the API sent its code (ADR-027): "Fehlgeschlagene
 * Prüfungen: IBAN." for "Failed checks: iban.". Other text, such as a user's reason or a parser
 * error, is shown as written.
 */
export function StatusReason({ reason }: { reason: Reason | null }) {
  const t = useTranslations("Codes.reason");
  const checkType = useCheckTypeLabel();
  if (reason === null) {
    return null;
  }
  const { text, code, checks } = reason;
  if (code === null || !isReasonCode(code)) {
    return text;
  }
  return code === "failed_checks"
    ? t("failed_checks", { checks: checks.map(checkType).join(", ") })
    : t(code);
}
