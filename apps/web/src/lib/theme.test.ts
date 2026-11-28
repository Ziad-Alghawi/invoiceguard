import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isDark, THEME_SCRIPT, themeFromCookie } from "@/lib/theme";

function clearCookie() {
  document.cookie = "THEME=; Path=/; Max-Age=0";
}

function runScript(systemDark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: systemDark, addEventListener: vi.fn() })),
  );
  // The script as the root layout puts it in <head>.
  new Function(THEME_SCRIPT)();
}

beforeEach(clearCookie);
afterEach(() => {
  clearCookie();
  vi.unstubAllGlobals();
  document.documentElement.className = "";
});

describe("theme", () => {
  it("reads the choice from the cookie, the system without one", () => {
    expect(themeFromCookie("")).toBe("system");
    expect(themeFromCookie("NEXT_LOCALE=de; THEME=dark")).toBe("dark");
    expect(themeFromCookie("THEME=light")).toBe("light");
    expect(themeFromCookie("THEME=purple")).toBe("system");
  });

  it("is dark when chosen, or by the system when the choice is the system", () => {
    expect(isDark("dark", false)).toBe(true);
    expect(isDark("light", true)).toBe(false);
    expect(isDark("system", true)).toBe(true);
    expect(isDark("system", false)).toBe(false);
  });

  it("the head script sets the class before the first paint", () => {
    runScript(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    document.cookie = "THEME=light; Path=/";
    runScript(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    document.cookie = "THEME=dark; Path=/";
    runScript(false);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });
});
