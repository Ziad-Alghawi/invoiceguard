"use client";

import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSelection } from "@/components/review-selection";
import { isFieldName } from "@/lib/codes";
import { confidencePercent, type InvoiceField } from "@/lib/invoices";
import {
  fieldKey,
  type FieldLocation,
  type Locations,
  locationsByKey,
} from "@/lib/locations";
import { cn } from "@/lib/utils";

/** Locations by field key; null when the document is not a PDF (nothing to locate). */
type Located = Map<string, FieldLocation> | null;

function FieldRows({
  fields,
  located,
}: {
  fields: InvoiceField[];
  located: Located;
}) {
  const t = useTranslations("Fields");
  const codes = useTranslations("Codes.field");
  const { selected, select } = useSelection();
  return fields.map((field) => {
    const key = fieldKey(field);
    const notLocated = located !== null && !located.get(key)?.located;
    const label = isFieldName(field.name) ? codes(field.name) : field.name;
    return (
      <tr
        key={key}
        data-low-confidence={field.low_confidence || undefined}
        data-selected={selected === key || undefined}
        className={cn(
          "border-t align-top",
          field.low_confidence && "bg-amber-500/10",
          selected === key && "bg-yellow-300/30",
        )}
      >
        <th scope="row" className="py-1.5 pr-3 text-left font-normal">
          <span className="block">{label}</span>
          <span className="text-xs text-muted-foreground">{field.code}</span>
        </th>
        <td className="py-1.5 pr-3 text-sm">
          <button
            type="button"
            aria-pressed={selected === key}
            aria-label={t("show", { field: label })}
            onClick={() => select(selected === key ? null : key)}
            className="text-left font-mono break-all underline decoration-dotted underline-offset-4 hover:decoration-solid"
          >
            {field.value}
          </button>
          {notLocated && (
            <span className="block text-xs text-muted-foreground">
              {t("notLocated")}
            </span>
          )}
        </td>
        <td className="py-1.5 text-sm">
          {field.source === "xml" ? (
            <span className="text-muted-foreground">{t("xml")}</span>
          ) : (
            <span className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "inline-flex items-center gap-1",
                  field.low_confidence && "font-medium text-amber-800",
                )}
              >
                {field.low_confidence && (
                  <TriangleAlert aria-hidden="true" className="size-3.5" />
                )}
                {t(field.low_confidence ? "llmLow" : "llm", {
                  confidence: confidencePercent(field.confidence) ?? "",
                })}
              </span>
              {field.evidence?.snippet && (
                <span className="text-xs text-muted-foreground">
                  {t("snippet", {
                    page: field.evidence.page ?? t("unknownPage"),
                    snippet: field.evidence.snippet,
                  })}
                </span>
              )}
            </span>
          )}
        </td>
      </tr>
    );
  });
}

function Table({
  caption,
  fields,
  located,
}: {
  caption: string;
  fields: InvoiceField[];
  located: Located;
}) {
  const t = useTranslations("Fields");
  return (
    <table className="w-full text-sm">
      <caption className="pb-1 text-left text-sm font-medium">
        {caption}
      </caption>
      <thead className="sr-only">
        <tr>
          <th scope="col">{t("field")}</th>
          <th scope="col">{t("value")}</th>
          <th scope="col">{t("source")}</th>
        </tr>
      </thead>
      <tbody>
        <FieldRows fields={fields} located={located} />
      </tbody>
    </table>
  );
}

/**
 * Extracted fields: document terms, then one table per invoice line. A value is a button: it
 * selects the field, and the document on the other side shows where it is printed.
 */
export function FieldsTable({
  fields,
  locations,
}: {
  fields: InvoiceField[];
  /** Where each value is in the PDF; without it (or for XML) nothing is marked "not located". */
  locations?: Locations;
}) {
  const located: Located = locations?.pdf ? locationsByKey(locations) : null;
  const t = useTranslations("Fields");
  if (fields.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("none")}</p>;
  }
  const documentFields = fields.filter((field) => field.line_no === null);
  const lineNumbers = [
    ...new Set(fields.flatMap((field) => field.line_no ?? [])),
  ];
  return (
    <div className="flex flex-col gap-4">
      <Table
        caption={t("document")}
        fields={documentFields}
        located={located}
      />
      {lineNumbers.map((lineNo) => (
        <Table
          key={lineNo}
          caption={t("line", { line: lineNo })}
          fields={fields.filter((field) => field.line_no === lineNo)}
          located={located}
        />
      ))}
    </div>
  );
}
