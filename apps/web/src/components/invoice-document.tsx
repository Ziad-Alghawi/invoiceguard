"use client";

import { useTranslations } from "next-intl";

import { PdfViewer } from "@/components/pdf-viewer";
import type { Invoice } from "@/lib/invoices";

/**
 * The left half of the split view: the invoice as the supplier sent it. A PDF is drawn with
 * pdf.js from the same route as the download.
 */
export function InvoiceDocument({
  invoice,
}: {
  invoice: Pick<Invoice, "id" | "source_type">;
}) {
  const t = useTranslations("Document");
  if (invoice.source_type === "pdf") {
    return <PdfViewer url={`/invoices/${invoice.id}/file`} highlights={[]} />;
  }
  return <p className="text-sm text-muted-foreground">{t("xmlOnly")}</p>;
}
