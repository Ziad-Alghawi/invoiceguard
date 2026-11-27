import { describe, expect, it } from "vitest";

import { highlightStyle } from "@/lib/locations";

describe("highlightStyle", () => {
  it("places a box in page fractions as percentages", () => {
    expect(
      highlightStyle({ page: 1, x0: 0.1, y0: 0.25, x1: 0.5, y1: 0.3 }),
    ).toEqual({
      left: "10.000%",
      top: "25.000%",
      width: "40.000%",
      height: "5.000%",
    });
  });

  it("keeps a box that runs past the page edge on the page", () => {
    expect(
      highlightStyle({ page: 1, x0: -0.1, y0: 0.9, x1: 0.2, y1: 1.2 }),
    ).toMatchObject({ left: "0.000%", top: "90.000%" });
  });
});
