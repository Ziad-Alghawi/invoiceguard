import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThemeSwitch } from "@/components/theme-switch";
import { THEME_SCRIPT } from "@/lib/theme";
import { renderWithIntl } from "@/test/intl";

afterEach(() => {
  cleanup();
  document.cookie = "THEME=; Path=/; Max-Age=0";
  vi.unstubAllGlobals();
  document.documentElement.className = "";
});

describe("ThemeSwitch", () => {
  it("keeps the choice in a cookie and applies it at once", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false, addEventListener: vi.fn() })),
    );
    new Function(THEME_SCRIPT)();
    renderWithIntl(<ThemeSwitch />, { locale: "de" });
    const group = screen.getByRole("group", { name: "Farbschema" });
    expect(group).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Wie das System" })
        .getAttribute("aria-pressed"),
    ).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Dunkel" }));
    expect(document.cookie).toContain("THEME=dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(
      screen
        .getByRole("button", { name: "Dunkel" })
        .getAttribute("aria-pressed"),
    ).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Wie das System" }));
    expect(document.cookie).not.toContain("THEME=");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
