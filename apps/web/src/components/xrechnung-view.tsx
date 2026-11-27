"use client";

import { useLocale, useTranslations } from "next-intl";

import { isLocale } from "@/i18n/config";
import { viewPath } from "@/lib/xrechnung";

/**
 * The e-invoice XML as the official KoSIT visualization, in a sandboxed iframe: no scripts, no
 * same origin, no forms. The clicked field reloads it with that term marked and in view.
 */
export function XRechnungView({
  invoiceId,
  field,
}: {
  invoiceId: string;
  field: { code: string; line_no: number | null } | null;
}) {
  const t = useTranslations("Document");
  const current = useLocale();
  const locale = isLocale(current) ? current : "de";
  return (
    <iframe
      sandbox=""
      src={viewPath(invoiceId, locale, field)}
      title={t("xrechnungTitle")}
      referrerPolicy="no-referrer"
      className="h-[80vh] w-full rounded-md border bg-white"
    />
  );
}
