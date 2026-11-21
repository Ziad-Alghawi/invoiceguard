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
    expect(exportSummary(RESULT)).toEqual([{ key: "exported", count: 1 }]);
    expect(exportSummary({ ...RESULT, invoiceCount: 3 })).toEqual([
      { key: "exported", count: 3 },
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
      { key: "exported", count: 4 },
      { key: "withoutTaxKey", count: 1 },
      { key: "withoutAccountSplit", count: 3 },
      { key: "remaining", count: 2 },
    ]);
  });
});

describe("exportFileHref", () => {
  it("points at the web server's download route", () => {
    expect(exportFileHref("e1")).toBe("/exports/datev/e1/file");
  });
});
