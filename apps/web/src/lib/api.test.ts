import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiPostAnonymous } from "@/lib/api";

const incoming = vi.hoisted(() => ({ headers: new Headers() }));

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
  headers: async () => incoming.headers,
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

describe("apiPostAnonymous", () => {
  const fetchMock = vi.fn(async () => new Response(null, { status: 401 }));

  beforeEach(() => {
    vi.stubEnv("API_URL", "http://api.test");
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    incoming.headers = new Headers();
    fetchMock.mockClear();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  function sentHeaders(): Headers {
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    return new Headers(init.headers);
  }

  it("passes the client address from the edge proxy on to the API", async () => {
    incoming.headers = new Headers({ "x-forwarded-for": "203.0.113.5" });

    await apiPostAnonymous("/auth/login", { email: "a@example.com" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
    expect(sentHeaders().get("x-forwarded-for")).toBe("203.0.113.5");
    expect(sentHeaders().get("content-type")).toBe("application/json");
  });

  it("sends no X-Forwarded-For when the request had none", async () => {
    await apiPostAnonymous("/auth/login", {});

    expect(sentHeaders().has("x-forwarded-for")).toBe(false);
  });
});
