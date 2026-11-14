import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DemoCredentials } from "@/components/demo-credentials";
import { getDemoLogin } from "@/lib/demo";

// Made up for the tests; the real demo password comes from the server environment.
const PASSWORD = "shared-demo-pass"; // pragma: allowlist secret

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("getDemoLogin", () => {
  it("is null unless both variables are set", () => {
    vi.stubEnv("DEMO_LOGIN_EMAIL", "");
    vi.stubEnv("DEMO_LOGIN_PASSWORD", "");
    expect(getDemoLogin()).toBeNull();
    vi.stubEnv("DEMO_LOGIN_EMAIL", "demo@example.com");
    expect(getDemoLogin()).toBeNull();
  });

  it("reads the demo account on every call", () => {
    vi.stubEnv("DEMO_LOGIN_EMAIL", "demo@example.com");
    vi.stubEnv("DEMO_LOGIN_PASSWORD", PASSWORD);
    expect(getDemoLogin()).toEqual({
      email: "demo@example.com",
      password: PASSWORD,
    });
  });
});

describe("DemoCredentials", () => {
  it("shows the email and password", () => {
    render(
      <DemoCredentials
        login={{ email: "demo@example.com", password: PASSWORD }}
      />,
    );
    const box = screen.getByRole("region", { name: "Demo login" });
    expect(box.textContent).toContain("demo@example.com");
    expect(box.textContent).toContain(PASSWORD);
  });
});
