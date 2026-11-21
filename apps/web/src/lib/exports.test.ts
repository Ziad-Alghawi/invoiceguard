import { describe, expect, it } from "vitest";

import { exportFileHref, exportSummary } from "@/lib/exports";

const RESULT = {
  id: "e1",
  invoiceCount: 1,
  withoutTaxKey: 0,
  withoutAccountSplit: 0,
  remaining: 0,
};

describe("exportSummary", () => {
  it("says how many invoices were exported", () => {
    expect(exportSummary(RESULT)).toEqual(["Exported 1 invoice to DATEV."]);
    expect(exportSummary({ ...RESULT, invoiceCount: 3 })).toEqual([
      "Exported 3 invoices to DATEV.",
    ]);
  });

  it("names invoices without a tax key or account split and those left for another file", () => {
    expect(
      exportSummary({
        ...RESULT,
        invoiceCount: 4,
        withoutTaxKey: 1,
        withoutAccountSplit: 3,
        remaining: 2,
      }),
    ).toEqual([
      "Exported 4 invoices to DATEV.",
      "1 invoice without a tax key (several or unknown VAT rates): set the tax in DATEV.",
      "3 invoices as one row (lines do not add up to the totals, for example a document discount): split by account in DATEV.",
      "2 invoices from a later fiscal year still waiting: export again.",
    ]);
  });
});

describe("exportFileHref", () => {
  it("points at the web server's download route", () => {
    expect(exportFileHref("e1")).toBe("/exports/datev/e1/file");
  });
});
