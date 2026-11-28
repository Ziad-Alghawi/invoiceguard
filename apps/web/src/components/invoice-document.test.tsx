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

vi.mock("@/components/xrechnung-view", () => ({
  XRechnungView: ({
    field,
  }: {
    field: { code: string; line_no: number | null } | null;
  }) => <div data-testid="xrechnung-view" data-field={field?.code ?? ""} />,
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

  it("shows an XML invoice as the XRechnung view, with the clicked term", () => {
    renderSplit("xml");
    expect(screen.queryByTestId("pdf-viewer")).toBeNull();
    expect(screen.queryByRole("group", { name: "Document view" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Show Payee IBAN in the document" }),
    );
    expect(screen.getByTestId("xrechnung-view").dataset.field).toBe("BT-84");
  });

  it("switches a ZUGFeRD PDF between the PDF and its e-invoice XML", () => {
    renderSplit("pdf", "de");
    const switcher = screen.getByRole("group", { name: "Dokumentansicht" });
    fireEvent.click(
      within(switcher).getByRole("button", { name: "E-Rechnung (XML)" }),
    );
    expect(screen.getByTestId("xrechnung-view")).toBeTruthy();
    expect(screen.queryByTestId("pdf-viewer")).toBeNull();
    fireEvent.click(within(switcher).getByRole("button", { name: "PDF" }));
    expect(screen.getByTestId("pdf-viewer")).toBeTruthy();
  });

  it("offers no XML view for a plain PDF read by the LLM", () => {
    renderWithIntl(
      <SelectionProvider>
        <InvoiceDocument
          invoice={{ id: ID, source_type: "pdf" }}
          fields={FIELDS.map((field) => ({ ...field, source: "llm" as const }))}
          locations={LOCATIONS}
        />
      </SelectionProvider>,
    );
    expect(screen.queryByRole("group")).toBeNull();
    expect(screen.getByTestId("pdf-viewer")).toBeTruthy();
  });
});
