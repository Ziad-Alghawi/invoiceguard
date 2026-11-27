import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InvoiceDocument } from "@/components/invoice-document";
import { renderWithIntl } from "@/test/intl";

vi.mock("@/components/pdf-viewer", () => ({
  PdfViewer: ({ url }: { url: string }) => (
    <div data-testid="pdf-viewer" data-url={url} />
  ),
}));

afterEach(cleanup);

const ID = "0b9d1c51-6f0e-4d0c-9f0a-1d2e3f405162";

describe("InvoiceDocument", () => {
  it("draws a PDF invoice from the file route", () => {
    renderWithIntl(
      <InvoiceDocument invoice={{ id: ID, source_type: "pdf" }} />,
    );
    expect(screen.getByTestId("pdf-viewer").dataset.url).toBe(
      `/invoices/${ID}/file`,
    );
  });

  it("says when there is no PDF to show", () => {
    renderWithIntl(
      <InvoiceDocument invoice={{ id: ID, source_type: "xml" }} />,
      {
        locale: "de",
      },
    );
    expect(screen.getByText(/XML-E-Rechnung ohne PDF/)).toBeTruthy();
  });
});
