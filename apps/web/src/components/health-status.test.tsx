import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthStatus } from "@/components/health-status";
import { checkApiHealth } from "@/lib/health";

afterEach(cleanup);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HealthStatus", () => {
  it("shows ok when the API is healthy", () => {
    render(<HealthStatus status="ok" />);
    expect(screen.getByRole("status").textContent).toBe("API: ok");
  });

  it("shows unreachable when the API is down", () => {
    render(<HealthStatus status="unreachable" />);
    expect(screen.getByRole("status").textContent).toBe("API: unreachable");
  });
});

describe("checkApiHealth", () => {
  it("returns ok for a 200 response with status ok", async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ status: "ok" }));
    await expect(checkApiHealth("http://api.test/", fetchFn)).resolves.toBe(
      "ok",
    );
    expect(fetchFn).toHaveBeenCalledWith(
      "http://api.test/health",
      expect.anything(),
    );
  });

  it("returns unreachable when the request fails", async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new TypeError("fetch failed"));
    await expect(checkApiHealth("http://api.test", fetchFn)).resolves.toBe(
      "unreachable",
    );
  });

  it("returns unreachable for a non-2xx response", async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({}, 503));
    await expect(checkApiHealth("http://api.test", fetchFn)).resolves.toBe(
      "unreachable",
    );
  });

  it("returns unreachable for an unexpected body", async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ status: "down" }));
    await expect(checkApiHealth("http://api.test", fetchFn)).resolves.toBe(
      "unreachable",
    );
  });

  it("returns unreachable without calling fetch when no base URL is set", async () => {
    const fetchFn = vi.fn<typeof fetch>();
    await expect(checkApiHealth(undefined, fetchFn)).resolves.toBe(
      "unreachable",
    );
    expect(fetchFn).not.toHaveBeenCalled();
  });
});
