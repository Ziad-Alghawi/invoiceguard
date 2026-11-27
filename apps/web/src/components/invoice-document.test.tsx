import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FieldsTable } from "@/components/fields-table";
import { InvoiceDocument } from "@/components/invoice-document";
import { SelectionProvider } from "@/components/review-selection";
import type { InvoiceField } from "@/lib/invoices";
import type { Highlight, Locations } from "@/lib/locations";
import { renderWithIntl } from "@/test/intl";

vi.mock("@/components/pdf-viewer", () => ({
  PdfViewer: ({
    url,
    highlights,
  }: {
    url: string;
    highlights: Highlight[];
  }) => (
    <div
      data-testid="pdf-viewer"
      data-url={url}
      data-highlights={JSON.stringify(highlights)}
    />
  ),
}));

afterEach(cleanup);

const ID = "0b9d1c51-6f0e-4d0c-9f0a-1d2e3f405162";
const BOX = { page: 1, x0: 0.1, y0: 0.8, x1: 0.5, y1: 0.82 };

const FIELDS: InvoiceField[] = [
  {
    code: "BT-84",
    name: "payee_iban",
    line_no: null,
    value: "DE60123456780000000003",
    source: "xml",
    confidence: null,
    low_confidence: false,
    evidence: null,
  },
  {
    code: "BT-27",
    name: "seller_name",
    line_no: null,
    value: "Demo IT-Service GmbH",
    source: "xml",
    confidence: null,
    low_confidence: false,
    evidence: null,
  },
];

const LOCATIONS: Locations = {
  pdf: true,
  fields: [
    {
      code: "BT-84",
      line_no: null,
      located: true,
      method: "text",
      boxes: [BOX],
    },
    { code: "BT-27", line_no: null, located: false, method: null, boxes: [] },
  ],
};

function renderSplit(source_type: "pdf" | "xml", locale: "de" | "en" = "en") {
  renderWithIntl(
    <SelectionProvider>
      <InvoiceDocument
        invoice={{ id: ID, source_type }}
        fields={FIELDS}
        locations={LOCATIONS}
      />
      <FieldsTable fields={FIELDS} locations={LOCATIONS} />
    </SelectionProvider>,
    { locale },
  );
}

function highlights(): Highlight[] {
  return JSON.parse(
    screen.getByTestId("pdf-viewer").dataset.highlights ?? "[]",
  ) as Highlight[];
}

describe("InvoiceDocument", () => {
  it("draws a PDF invoice from the file route, nothing marked at first", () => {
    renderSplit("pdf");
    expect(screen.getByTestId("pdf-viewer").dataset.url).toBe(
      `/invoices/${ID}/file`,
    );
    expect(highlights()).toEqual([]);
  });

  it("marks the clicked field's place and unmarks it on a second click", () => {
    renderSplit("pdf");
    const show = screen.getByRole("button", {
      name: "Show Payee IBAN in the document",
    });
    fireEvent.click(show);
    expect(highlights()).toEqual([BOX]);
    expect(show.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(show);
    expect(highlights()).toEqual([]);
  });

  it("says so when a clicked field is not in the text layer", () => {
    renderSplit("pdf", "de");
    const row = screen.getByRole("row", { name: /Verkäufer/ });
    expect(within(row).getByText("nicht gefunden")).toBeTruthy();
    fireEvent.click(within(row).getByRole("button"));
    expect(screen.getByRole("status").textContent).toMatch(
      /im Text des PDFs nicht gefunden/,
    );
    expect(highlights()).toEqual([]);
  });

  it("says when there is no PDF to show", () => {
    renderSplit("xml", "de");
    expect(screen.getByText(/XML-E-Rechnung ohne PDF/)).toBeTruthy();
  });
});
