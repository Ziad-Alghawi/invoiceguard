/** The readable XRechnung view (ADR-029): which page of the API's view to show. */

import { isLocale, type Locale } from "@/i18n/config";

const TERM = /^BT-\d{1,3}$/;

/** The view's path for a language and, optionally, the clicked field; scrolls to the mark. */
export function viewPath(
  invoiceId: string,
  locale: Locale,
  field: { code: string; line_no: number | null } | null,
): string {
  const query = new URLSearchParams({ lang: locale });
  if (field !== null && TERM.test(field.code)) {
    query.set("highlight", field.code);
    if (field.line_no !== null) {
      query.set("line", String(field.line_no));
    }
    return `/invoices/${invoiceId}/view?${query}#highlight`;
  }
  return `/invoices/${invoiceId}/view?${query}`;
}

/** The query passed on to the API, or null when a parameter is not one the view knows. */
export function viewQuery(params: URLSearchParams): URLSearchParams | null {
  const lang = params.get("lang") ?? "de";
  const highlight = params.get("highlight");
  const line = params.get("line");
  if (!isLocale(lang)) {
    return null;
  }
  const query = new URLSearchParams({ lang });
  if (highlight !== null) {
    if (!TERM.test(highlight)) {
      return null;
    }
    query.set("highlight", highlight);
  }
  if (line !== null) {
    if (!/^[1-9]\d{0,3}$/.test(line)) {
      return null;
    }
    query.set("line", line);
  }
  return query;
}
