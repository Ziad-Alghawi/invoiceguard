import { describe, expect, it } from "vitest";

import { viewPath, viewQuery } from "@/lib/xrechnung";

const ID = "0b9d1c51-6f0e-4d0c-9f0a-1d2e3f405162";

describe("viewPath", () => {
  it("asks for the language, and the clicked term with its line, scrolled into view", () => {
    expect(viewPath(ID, "en", null)).toBe(`/invoices/${ID}/view?lang=en`);
    expect(viewPath(ID, "de", { code: "BT-84", line_no: null })).toBe(
      `/invoices/${ID}/view?lang=de&highlight=BT-84#highlight`,
    );
    expect(viewPath(ID, "de", { code: "BT-153", line_no: 2 })).toBe(
      `/invoices/${ID}/view?lang=de&highlight=BT-153&line=2#highlight`,
    );
  });
});

describe("viewQuery", () => {
  it("passes on what the view knows, German by default", () => {
    expect(viewQuery(new URLSearchParams())?.toString()).toBe("lang=de");
    expect(
      viewQuery(
        new URLSearchParams("lang=en&highlight=BT-1&line=3"),
      )?.toString(),
    ).toBe("lang=en&highlight=BT-1&line=3");
  });

  it.each([
    "lang=ar",
    "highlight=BT-1%27",
    "highlight=xyz",
    "line=0",
    "line=-1",
  ])("refuses %s", (query) => {
    expect(viewQuery(new URLSearchParams(query))).toBeNull();
  });
});
