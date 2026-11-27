/**
 * Light or dark (P1). The choice is kept in a cookie like the language (ADR-027); without one the
 * system setting decides. An inline script applies it before the first paint, so there is no
 * flash of the wrong colours.
 */

export const THEMES = ["system", "light", "dark"] as const;

export type Theme = (typeof THEMES)[number];

export const THEME_COOKIE = "THEME";

/** One year, like the language. */
export const THEME_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && THEMES.some((theme) => theme === value);
}

/** The theme in a cookie header, "system" when there is none. */
export function themeFromCookie(cookie: string): Theme {
  const match = new RegExp(`(?:^|; )${THEME_COOKIE}=([a-z]+)`).exec(cookie);
  return match && isTheme(match[1]) ? match[1] : "system";
}

/** Whether a theme shows dark colours, given the system's preference. */
export function isDark(theme: Theme, systemDark: boolean): boolean {
  return theme === "dark" || (theme === "system" && systemDark);
}

/**
 * Runs in <head> before the first paint: sets the `dark` class from the cookie or the system,
 * and follows the system while the choice is "system".
 */
export const THEME_SCRIPT = `(function(){var d=document.documentElement,q=window.matchMedia("(prefers-color-scheme: dark)");function a(){var m=document.cookie.match(/(?:^|; )${THEME_COOKIE}=(light|dark)(?:;|$)/),t=m?m[1]:"system";d.classList.toggle("dark",t==="dark"||(t==="system"&&q.matches));d.style.colorScheme=d.classList.contains("dark")?"dark":"light";}a();q.addEventListener("change",a);window.__applyTheme=a;})();`;
