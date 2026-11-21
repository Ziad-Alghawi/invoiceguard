/** The DATEV export (ADR-013) as the web app shows it. */

export type DatevExport = {
  id: string;
  invoiceCount: number;
  /** Exported without a BU key: the tax advisor sets the tax in DATEV. */
  withoutTaxKey: number;
  /** Booked to several accounts, but exported as one row: the lines do not add up to the totals. */
  withoutAccountSplit: number;
  /** Approved invoices from a later fiscal year, for the next export. */
  remaining: number;
};

export type ExportState = { error: string | null; export: DatevExport | null };

/** Where the browser downloads an export's file (through the web server, never the API). */
export function exportFileHref(id: string): string {
  return `/exports/datev/${id}/file`;
}

/** One line of the summary: a message key in "Export" and its invoice count. */
export type ExportLine = {
  key: "exported" | "withoutTaxKey" | "withoutAccountSplit" | "remaining";
  count: number;
};

/** "Exported 2 invoices to DATEV." plus what the reviewer still has to do. */
export function exportSummary(result: DatevExport): ExportLine[] {
  const lines: ExportLine[] = [{ key: "exported", count: result.invoiceCount }];
  const followUps = [
    { key: "withoutTaxKey", count: result.withoutTaxKey },
    { key: "withoutAccountSplit", count: result.withoutAccountSplit },
    { key: "remaining", count: result.remaining },
  ] as const;
  for (const line of followUps) {
    if (line.count > 0) {
      lines.push(line);
    }
  }
  return lines;
}
