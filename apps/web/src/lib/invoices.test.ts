import { describe, expect, it } from "vitest";

import {
  canApprove,
  canReject,
  confidencePercent,
  fieldLabel,
  isInvoiceId,
  isQueueFilter,
} from "@/lib/invoices";

describe("fieldLabel", () => {
  it("turns API field names into labels", () => {
    expect(fieldLabel("payee_iban")).toBe("Payee IBAN");
    expect(fieldLabel("seller_vat_id")).toBe("Seller VAT ID");
    expect(fieldLabel("gross_total")).toBe("Gross Total");
  });
});

describe("confidencePercent", () => {
  it("shows LLM confidence as a percentage and nothing for XML", () => {
    expect(confidencePercent("0.550")).toBe("55 %");
    expect(confidencePercent("1.000")).toBe("100 %");
    expect(confidencePercent(null)).toBeNull();
  });
});

describe("decision rules", () => {
  it("match the API: approve ready or blocked, reject also failed or waiting", () => {
    expect(canApprove("ready")).toBe(true);
    expect(canApprove("blocked")).toBe(true);
    expect(canApprove("failed")).toBe(false);
    expect(canApprove("approved")).toBe(false);
    expect(canReject("failed")).toBe(true);
    expect(canReject("awaiting_extraction")).toBe(true);
    expect(canReject("processing")).toBe(false);
    expect(canReject("rejected")).toBe(false);
  });
});

describe("input checks", () => {
  it("accept only known queue filters", () => {
    expect(isQueueFilter("blocked")).toBe(true);
    expect(isQueueFilter("toString")).toBe(false);
    expect(isQueueFilter(["blocked"])).toBe(false);
  });

  it("accept only UUIDs as invoice IDs", () => {
    expect(isInvoiceId("6f1c2a52-8d0e-4c43-9a55-0c1f0f8a2b11")).toBe(true);
    expect(isInvoiceId("../auth/logout")).toBe(false);
  });
});
