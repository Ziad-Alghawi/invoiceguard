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

function invoices(count: number): string {
  return count === 1 ? "1 invoice" : `${count} invoices`;
}

/** "Exported 2 invoices to DATEV." plus what the reviewer still has to do. */
export function exportSummary(result: DatevExport): string[] {
  const lines = [`Exported ${invoices(result.invoiceCount)} to DATEV.`];
  if (result.withoutTaxKey > 0) {
    lines.push(
      `${invoices(result.withoutTaxKey)} without a tax key (several or unknown VAT rates): set the tax in DATEV.`,
    );
  }
  if (result.withoutAccountSplit > 0) {
    lines.push(
      `${invoices(result.withoutAccountSplit)} as one row (lines do not add up to the totals, for example a document discount): split by account in DATEV.`,
    );
  }
  if (result.remaining > 0) {
    lines.push(
      `${invoices(result.remaining)} from a later fiscal year still waiting: export again.`,
    );
  }
  return lines;
}
