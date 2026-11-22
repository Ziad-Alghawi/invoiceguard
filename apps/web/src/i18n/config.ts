/**
 * The UI languages (ADR-027). German is the default; the choice is kept in a cookie, not in the
 * URL, so every path stays the same in both languages.
 */

export const LOCALES = ["de", "en"] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "de";

/** next-intl's cookie name; set by the language switch (setLocale in app/actions.ts). */
export const LOCALE_COOKIE = "NEXT_LOCALE";

/** One year: the choice should outlast the session. */
export const LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

/** Dates and times are shown in the company's time zone, in both languages. */
export const TIME_ZONE = "Europe/Berlin";

export function isLocale(value: unknown): value is Locale {
  return (
    typeof value === "string" && LOCALES.some((locale) => locale === value)
  );
}

/**
 * Runs in <head> before the first paint and sets <html lang> from the cookie. The root layout
 * cannot read the cookie itself without making every page request-bound (cacheComponents).
 */
export const HTML_LANG_SCRIPT = `(function(){var m=document.cookie.match(/(?:^|; )${LOCALE_COOKIE}=(${LOCALES.join("|")})(?:;|$)/);document.documentElement.lang=m?m[1]:"${DEFAULT_LOCALE}";})();`;
