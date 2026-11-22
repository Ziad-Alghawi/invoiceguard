import { describe, expect, it } from "vitest";

import {
  bookingsFromForm,
  type LineBooking,
  preselected,
  suggestionNote,
} from "@/lib/bookings";

const LINE: LineBooking = {
  line_no: 1,
  text: "Notebook 14 Zoll",
  method: "vector",
  suggestions: [
    {
      account: "0410",
      name: "Geschäftsausstattung",
      share: 0.917,
      sources: [
        {
          invoice_id: null,
          invoice_number: "IT-2025-0004",
          issue_date: "2025-03-02",
          supplier_name: "Demo IT-Service GmbH",
          text: "Notebook 14 Zoll, 32 GB RAM",
          account: "0410",
          same_supplier: true,
          similarity: 0.98,
        },
      ],
    },
  ],
  booked: null,
};
const EMPTY: LineBooking = { ...LINE, method: "text", suggestions: [] };

describe("bookings", () => {
  it("preselects the top suggestion, else the default account", () => {
    expect(preselected(LINE, "4900")).toBe("0410");
    expect(preselected(EMPTY, "4900")).toBe("4900");
  });

  it("reads the chosen accounts per line from the form, in line order", () => {
    const form = new FormData();
    form.set("account-2", "4806");
    form.set("account-1", "0410");
    form.set("approver_reason", "ok");

    expect(bookingsFromForm(form)).toEqual([
      { line_no: 1, account: "0410" },
      { line_no: 2, account: "4806" },
    ]);
  });

  it("explains the suggestion with its sources", () => {
    expect(suggestionNote(LINE, "imported")).toEqual({
      account: "0410",
      name: "Geschäftsausstattung",
      share: 92,
      method: "vector",
      sources: "IT-2025-0004, Demo IT-Service GmbH",
    });
    expect(suggestionNote(EMPTY, "imported")).toBeNull();
  });
});
