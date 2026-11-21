import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportButton } from "@/components/export-button";
import type { ExportState } from "@/lib/exports";

afterEach(cleanup);

function exported(state: ExportState) {
  return vi.fn<() => Promise<ExportState>>().mockResolvedValue(state);
}

describe("ExportButton", () => {
  it("exports, shows the count and starts the download", async () => {
    const startDownload = vi.fn<(href: string) => void>();
    const exportDatev = exported({
      error: null,
      export: {
        id: "e1",
        invoiceCount: 2,
        withoutTaxKey: 0,
        withoutAccountSplit: 0,
        remaining: 0,
      },
    });
    render(
      <ExportButton exportDatev={exportDatev} startDownload={startDownload} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Export to DATEV" }));

    expect((await screen.findByRole("status")).textContent).toContain(
      "Exported 2 invoices to DATEV.",
    );
    await waitFor(() =>
      expect(startDownload).toHaveBeenCalledWith("/exports/datev/e1/file"),
    );
    expect(startDownload).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("link", { name: "Download again" }).getAttribute("href"),
    ).toBe("/exports/datev/e1/file");
  });

  it("shows the API's message when nothing is waiting", async () => {
    const startDownload = vi.fn<(href: string) => void>();
    const exportDatev = exported({
      error: "No approved invoices are waiting for export.",
      export: null,
    });
    render(
      <ExportButton exportDatev={exportDatev} startDownload={startDownload} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Export to DATEV" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "No approved invoices are waiting for export.",
    );
    expect(startDownload).not.toHaveBeenCalled();
  });
});
