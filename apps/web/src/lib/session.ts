/** The API's session cookie (ADR-011), as the web server receives and re-issues it. */

export const SESSION_COOKIE = "invoiceguard_session";

export type SessionCookie = {
  token: string;
  maxAge: number | undefined;
  secure: boolean;
};

/**
 * Reads the session cookie from the API's `Set-Cookie` headers after login.
 * The web server sets the same cookie for the browser, with the same lifetime and the same
 * `Secure` flag the API chose (Secure only in prod), so both sides agree on the session.
 */
export function parseSessionCookie(
  setCookieHeaders: string[],
): SessionCookie | null {
  for (const header of setCookieHeaders) {
    const [pair, ...attributes] = header.split(";").map((part) => part.trim());
    const separator = pair.indexOf("=");
    if (separator < 0 || pair.slice(0, separator) !== SESSION_COOKIE) {
      continue;
    }
    const token = pair.slice(separator + 1);
    if (!token) {
      return null;
    }
    let maxAge: number | undefined;
    let secure = false;
    for (const attribute of attributes) {
      const [key, value] = attribute.split("=");
      if (key.toLowerCase() === "max-age" && value !== undefined) {
        maxAge = Number(value);
      } else if (key.toLowerCase() === "secure") {
        secure = true;
      }
    }
    return { token, maxAge, secure };
  }
  return null;
}
