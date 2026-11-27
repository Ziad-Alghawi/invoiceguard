"use client";

import { useTranslations } from "next-intl";

import { PdfViewer } from "@/components/pdf-viewer";
import { useSelection } from "@/components/review-selection";
import { isFieldName } from "@/lib/codes";
import type { Invoice, InvoiceField } from "@/lib/invoices";
import { fieldKey, type Locations, locationsByKey } from "@/lib/locations";

/**
 * The left half of the split view: the invoice as the supplier sent it. A PDF is drawn with
 * pdf.js from the same route as the download, with the clicked field's place marked.
 */
export function InvoiceDocument({
  invoice,
  fields,
  locations,
}: {
  invoice: Pick<Invoice, "id" | "source_type">;
  fields: InvoiceField[];
  locations: Locations;
}) {
  const t = useTranslations("Document");
  const codes = useTranslations("Codes.field");
  const { selected } = useSelection();
  if (invoice.source_type !== "pdf") {
    return <p className="text-sm text-muted-foreground">{t("xmlOnly")}</p>;
  }
  const location =
    selected === null ? undefined : locationsByKey(locations).get(selected);
  const field = fields.find((candidate) => fieldKey(candidate) === selected);
  const label =
    field && isFieldName(field.name) ? codes(field.name) : (field?.name ?? "");
  return (
    <div className="flex flex-col gap-2">
      {selected !== null && !location?.located && (
        <p role="status" className="text-sm text-amber-800">
          {t("notLocated", { field: label })}
        </p>
      )}
      <PdfViewer
        url={`/invoices/${invoice.id}/file`}
        highlights={location?.boxes ?? []}
      />
    </div>
  );
}
