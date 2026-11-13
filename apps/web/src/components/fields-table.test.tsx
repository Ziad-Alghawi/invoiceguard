import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FieldsTable } from "@/components/fields-table";
import type { InvoiceField } from "@/lib/invoices";

afterEach(cleanup);

function field(overrides: Partial<InvoiceField>): InvoiceField {
  return {
    code: "BT-1",
    name: "invoice_number",
    line_no: null,
    value: "2026-IT-0815",
    source: "xml",
    confidence: null,
    low_confidence: false,
    evidence: null,
    ...overrides,
  };
}

describe("FieldsTable", () => {
  it("highlights low-confidence fields with their evidence", () => {
    render(
      <FieldsTable
        fields={[
          field({ source: "llm", confidence: "0.950" }),
          field({
            code: "BT-84",
            name: "payee_iban",
            value: "DE60123456780000000003",
            source: "llm",
            confidence: "0.550",
            low_confidence: true,
            evidence: { page: 1, snippet: "IBAN DE60 1234" },
          }),
        ]}
      />,
    );

    const iban = screen.getByRole("row", { name: /Payee IBAN/ });
    expect(iban.dataset.lowConfidence).toBe("true");
    expect(within(iban).getByText(/LLM 55 %/).textContent).toContain(
      "low confidence, check the PDF",
    );
    expect(within(iban).getByText(/IBAN DE60 1234/)).toBeTruthy();

    const number = screen.getByRole("row", { name: /Invoice Number/ });
    expect(number.dataset.lowConfidence).toBeUndefined();
    expect(within(number).getByText("LLM 95 %")).toBeTruthy();
  });

  it("groups line fields by line and marks XML values", () => {
    render(
      <FieldsTable
        fields={[
          field({}),
          field({
            code: "BT-153",
            name: "item_name",
            line_no: 1,
            value: "Notebook",
          }),
          field({
            code: "BT-153",
            name: "item_name",
            line_no: 2,
            value: "Setup",
          }),
        ]}
      />,
    );

    const captions = screen
      .getAllByRole("table")
      .map((table) => table.querySelector("caption")?.textContent);
    expect(captions).toEqual(["Document", "Line 1", "Line 2"]);
    expect(screen.getAllByText("XML")).toHaveLength(3);
  });

  it("says so when nothing was extracted", () => {
    render(<FieldsTable fields={[]} />);
    expect(screen.getByText("No fields extracted yet.")).toBeTruthy();
  });
});
