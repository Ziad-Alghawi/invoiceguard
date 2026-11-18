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
    expect(checkFile({ name: "rechnung.docx", size: 10 })).toMatch(
      /\.xml or \.pdf/,
    );
    expect(checkFile({ name: "rechnung.xml", size: 0 })).toBe(
      "The file is empty.",
    );
    expect(
      checkFile({ name: "rechnung.pdf", size: MAX_UPLOAD_BYTES + 1 }),
    ).toBe("The file is larger than 10 MB.");
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
      message: "This file was already uploaded.",
      existingId: "old",
    });
  });

  it.each([
    [413, "File is larger than 10485760 bytes."],
    [
      415,
      "Upload an XML or PDF invoice; the file extension must match its content.",
    ],
    [422, "This PDF has no embedded e-invoice XML."],
    [429, "Upload limit reached: 30 files per hour. Try again later."],
  ])("shows the API's message for %i", (status, detail) => {
    expect(uploadOutcome({ status, body: { detail } })).toEqual({
      kind: "error",
      message: detail,
      existingId: null,
    });
  });

  it("has its own message when the API sends no detail", () => {
    expect(uploadOutcome({ status: 413, body: null })).toMatchObject({
      message: "The file is too large.",
    });
    expect(uploadOutcome({ status: 401, body: null })).toMatchObject({
      message: "Your session has ended. Log in again.",
    });
    expect(uploadOutcome({ status: 502, body: null })).toMatchObject({
      message: "The upload failed (502).",
    });
  });
});

describe("statusSummary", () => {
  it("explains the status after processing", () => {
    expect(statusSummary("ready")).toMatch(/ready for review/);
    expect(statusSummary("blocked")).toMatch(/blocked/);
    expect(statusSummary("override_requested")).toBe(
      "The invoice is override requested.",
    );
  });
});
