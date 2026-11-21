import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StatusState } from "@/app/actions";
import { UploadForm } from "@/components/upload-form";
import type { UploadResponse } from "@/lib/upload";
import { renderWithIntl } from "@/test/intl";

afterEach(cleanup);

type Send = (
  file: File,
  onProgress: (percent: number) => void,
) => Promise<UploadResponse>;

function choose(name: string, content = "<Invoice/>") {
  const input = screen.getByLabelText("Invoice file");
  fireEvent.change(input, {
    target: { files: [new File([content], name)] },
  });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
}

describe("UploadForm", () => {
  it("uploads, waits for processing and links to the invoice", async () => {
    const send = vi.fn<Send>(async (_file, onProgress) => {
      onProgress(50);
      return { status: 202, body: { id: "inv-1" } };
    });
    const getStatus = vi
      .fn<(id: string) => Promise<StatusState>>()
      .mockResolvedValueOnce({
        status: "processing",
        reason: null,
        error: null,
      })
      .mockResolvedValueOnce({
        status: "blocked",
        reason: "Failed checks: iban.",
        error: null,
      });
    renderWithIntl(
      <UploadForm send={send} getStatus={getStatus} pollIntervalMs={1} />,
    );

    choose("rechnung.xml");
    submit();

    const status = await screen.findByText(/The invoice is blocked/);
    expect(status).toBeTruthy();
    expect(screen.getByText("Failed checks: iban.")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open the invoice" })
        .getAttribute("href"),
    ).toBe("/invoices/inv-1");
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(getStatus).toHaveBeenCalledWith("inv-1");
  });

  it("refuses a wrong file type without sending it", async () => {
    const send = vi.fn<Send>();
    renderWithIntl(<UploadForm send={send} getStatus={vi.fn()} />);

    choose("rechnung.docx");
    submit();

    expect((await screen.findByRole("alert")).textContent).toMatch(
      /\.xml or \.pdf/,
    );
    expect(send).not.toHaveBeenCalled();
  });

  it("asks for a file when none is chosen", async () => {
    renderWithIntl(<UploadForm send={vi.fn<Send>()} getStatus={vi.fn()} />);

    submit();

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Choose a file to upload.",
    );
  });

  it("shows the demo message for a PDF without XML", async () => {
    const detail = "This PDF has no embedded e-invoice XML.";
    const send = vi
      .fn<Send>()
      .mockResolvedValue({ status: 422, body: { detail } });
    const getStatus = vi.fn();
    renderWithIntl(<UploadForm send={send} getStatus={getStatus} />);

    choose("scan.pdf", "%PDF-1.7");
    submit();

    expect((await screen.findByRole("alert")).textContent).toBe(detail);
    expect(getStatus).not.toHaveBeenCalled();
  });

  it("links a duplicate to the existing invoice", async () => {
    const send = vi.fn<Send>().mockResolvedValue({
      status: 409,
      body: { detail: { message: "x", invoice_id: "old-1" } },
    });
    renderWithIntl(<UploadForm send={send} getStatus={vi.fn()} />);

    choose("rechnung.xml");
    submit();

    await waitFor(() =>
      expect(
        screen
          .getByRole("link", { name: "Open the existing invoice" })
          .getAttribute("href"),
      ).toBe("/invoices/old-1"),
    );
  });

  it("shows an interrupted upload", async () => {
    const send = vi
      .fn<Send>()
      .mockRejectedValue(new Error("The upload was interrupted."));
    renderWithIntl(<UploadForm send={send} getStatus={vi.fn()} />);

    choose("rechnung.xml");
    submit();

    expect((await screen.findByRole("alert")).textContent).toBe(
      "The upload was interrupted.",
    );
  });
});
