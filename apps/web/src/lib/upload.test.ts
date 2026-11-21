import { describe, expect, it } from "vitest";

import {
  checkFile,
  MAX_UPLOAD_BYTES,
  statusSummary,
  uploadOutcome,
} from "@/lib/upload";

describe("checkFile", () => {
  it("accepts XML and PDF files within the limit, in any case", () => {
    expect(checkFile({ name: "rechnung.xml", size: 10 })).toBeNull();
    expect(
      checkFile({ name: "RECHNUNG.PDF", size: MAX_UPLOAD_BYTES }),
    ).toBeNull();
  });

  it("refuses other types, empty and too large files", () => {
    expect(checkFile({ name: "rechnung.docx", size: 10 })).toEqual({
      key: "wrongType",
    });
    expect(checkFile({ name: "rechnung.xml", size: 0 })).toEqual({
      key: "empty",
    });
    expect(
      checkFile({ name: "rechnung.pdf", size: MAX_UPLOAD_BYTES + 1 }),
    ).toEqual({ key: "tooLarge", values: { mb: 10 } });
  });
});

describe("uploadOutcome", () => {
  it("returns the new invoice on 202", () => {
    expect(uploadOutcome({ status: 202, body: { id: "abc" } })).toEqual({
      kind: "accepted",
      invoiceId: "abc",
    });
  });

  it("links a duplicate to the invoice that already exists", () => {
    const body = {
      detail: { message: "This file was already uploaded.", invoice_id: "old" },
    };
    expect(uploadOutcome({ status: 409, body })).toEqual({
      kind: "error",
      detail: null,
      problem: { key: "duplicate" },
      existingId: "old",
    });
  });

  it.each([
    [413, "tooLargeApi", "File is larger than 10485760 bytes."],
    [
      415,
      "unsupported",
      "Upload an XML or PDF invoice; the file extension must match its content.",
    ],
    [
      429,
      "tooMany",
      "Upload limit reached: 30 files per hour. Try again later.",
    ],
  ])("keeps the API's message for %i", (status, key, detail) => {
    expect(uploadOutcome({ status, body: { detail } })).toEqual({
      kind: "error",
      detail,
      problem: { key },
      existingId: null,
    });
  });

  it("keeps the API's message for other errors, with the status as fallback", () => {
    const detail = "This PDF has no embedded e-invoice XML.";
    expect(uploadOutcome({ status: 422, body: { detail } })).toEqual({
      kind: "error",
      detail,
      problem: { key: "failed", values: { status: 422 } },
      existingId: null,
    });
  });

  it("has its own message when the API sends no detail", () => {
    expect(uploadOutcome({ status: 413, body: null })).toMatchObject({
      detail: null,
      problem: { key: "tooLargeApi" },
    });
    expect(uploadOutcome({ status: 401, body: null })).toMatchObject({
      detail: null,
      problem: { key: "session" },
    });
    expect(uploadOutcome({ status: 502, body: null })).toMatchObject({
      detail: null,
      problem: { key: "failed", values: { status: 502 } },
    });
    expect(uploadOutcome({ status: 202, body: {} })).toMatchObject({
      problem: { key: "noInvoice" },
    });
  });
});

describe("statusSummary", () => {
  it("explains the status after processing", () => {
    expect(statusSummary("ready")).toBe("ready");
    expect(statusSummary("blocked")).toBe("blocked");
    expect(statusSummary("awaiting_extraction")).toBe("awaitingExtraction");
    expect(statusSummary("failed")).toBe("failed");
    expect(statusSummary("override_requested")).toBe("other");
  });
});
