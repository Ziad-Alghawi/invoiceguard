import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { isFieldName } from "@/lib/codes";
import { confidencePercent, type InvoiceField } from "@/lib/invoices";
import { cn } from "@/lib/utils";

function FieldRows({ fields }: { fields: InvoiceField[] }) {
  const t = useTranslations("Fields");
  const codes = useTranslations("Codes.field");
  return fields.map((field) => (
    <tr
      key={`${field.code}-${field.line_no ?? "doc"}`}
      data-low-confidence={field.low_confidence || undefined}
      className={cn(
        "border-t align-top",
        field.low_confidence && "bg-amber-500/10",
      )}
    >
      <th scope="row" className="py-1.5 pr-3 text-left font-normal">
        <span className="block">
          {isFieldName(field.name) ? codes(field.name) : field.name}
        </span>
        <span className="text-xs text-muted-foreground">{field.code}</span>
      </th>
      <td className="py-1.5 pr-3 font-mono text-sm break-all">{field.value}</td>
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
  ));
}

function Table({
  caption,
  fields,
}: {
  caption: string;
  fields: InvoiceField[];
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
        <FieldRows fields={fields} />
      </tbody>
    </table>
  );
}

/** Extracted fields: document terms, then one table per invoice line. */
export function FieldsTable({ fields }: { fields: InvoiceField[] }) {
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
      <Table caption={t("document")} fields={documentFields} />
      {lineNumbers.map((lineNo) => (
        <Table
          key={lineNo}
          caption={t("line", { line: lineNo })}
          fields={fields.filter((field) => field.line_no === lineNo)}
        />
      ))}
    </div>
  );
}
