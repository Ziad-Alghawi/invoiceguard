"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { PdfViewer } from "@/components/pdf-viewer";
import { useSelection } from "@/components/review-selection";
import { XRechnungView } from "@/components/xrechnung-view";
import { isFieldName } from "@/lib/codes";
import type { Invoice, InvoiceField } from "@/lib/invoices";
import { fieldKey, type Locations, locationsByKey } from "@/lib/locations";
import { cn } from "@/lib/utils";

type View = "pdf" | "xml";

/**
 * The left half of the split view: the invoice as the supplier sent it. A PDF is drawn with
 * pdf.js, with the clicked field's place marked; e-invoice XML is shown as the KoSIT
 * visualization with the clicked term marked. A ZUGFeRD PDF has both, one at a time.
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
  const isPdf = invoice.source_type === "pdf";
  const hasXml = !isPdf || fields.some((field) => field.source === "xml");
  const [view, setView] = useState<View>(isPdf ? "pdf" : "xml");
  const field =
    fields.find((candidate) => fieldKey(candidate) === selected) ?? null;

  if (view === "xml" || !isPdf) {
    return (
      <div className="flex flex-col gap-2">
        {isPdf && <ViewSwitch view={view} setView={setView} />}
        <XRechnungView invoiceId={invoice.id} field={field} />
      </div>
    );
  }
  const location =
    selected === null ? undefined : locationsByKey(locations).get(selected);
  const label =
    field && isFieldName(field.name) ? codes(field.name) : (field?.name ?? "");
  return (
    <div className="flex flex-col gap-2">
      {hasXml && <ViewSwitch view={view} setView={setView} />}
      {field !== null && !location?.located && (
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

function ViewSwitch({
  view,
  setView,
}: {
  view: View;
  setView: (view: View) => void;
}) {
  const t = useTranslations("Document");
  return (
    <div
      role="group"
      aria-label={t("viewLabel")}
      className="flex gap-1 self-start rounded-md border p-0.5 text-sm"
    >
      {(["pdf", "xml"] as const).map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={view === option}
          onClick={() => setView(option)}
          className={cn(
            "rounded px-2 py-0.5",
            view === option && "bg-primary text-primary-foreground",
          )}
        >
          {t(option === "pdf" ? "viewPdf" : "viewXml")}
        </button>
      ))}
    </div>
  );
}
