import { describe, expect, it } from "vitest";

import { parseSessionCookie } from "@/lib/session";

describe("parseSessionCookie", () => {
  it("reads the token, lifetime and Secure flag", () => {
    expect(
      parseSessionCookie([
        "other=1; Path=/",
        "invoiceguard_session=abc-123_x; HttpOnly; Max-Age=28800; Path=/; SameSite=lax; Secure",
      ]),
    ).toEqual({ token: "abc-123_x", maxAge: 28800, secure: true });
  });

  it("is not secure when the API did not set Secure (dev)", () => {
    expect(
      parseSessionCookie([
        "invoiceguard_session=abc; HttpOnly; Max-Age=60; Path=/; SameSite=lax",
      ]),
    ).toEqual({ token: "abc", maxAge: 60, secure: false });
  });

  it("returns null without a session cookie or with an empty one", () => {
    expect(parseSessionCookie([])).toBeNull();
    expect(parseSessionCookie(["invoiceguard_sessionx=abc"])).toBeNull();
    expect(parseSessionCookie(["invoiceguard_session=; Path=/"])).toBeNull();
  });
});
