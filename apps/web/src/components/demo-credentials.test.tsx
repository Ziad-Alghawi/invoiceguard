import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DemoCredentials } from "@/components/demo-credentials";
import { getDemoLogins } from "@/lib/demo";

// Made up for the tests; the real demo passwords come from the server environment.
const PASSWORD = "shared-demo-pass"; // pragma: allowlist secret
const APPROVER_PASSWORD = "shared-approver-pass"; // pragma: allowlist secret
const VARIABLES = [
  "DEMO_LOGIN_EMAIL",
  "DEMO_LOGIN_PASSWORD",
  "DEMO_APPROVER_EMAIL",
  "DEMO_APPROVER_PASSWORD",
];

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

function stub(values: Record<string, string>) {
  for (const name of VARIABLES) {
    vi.stubEnv(name, values[name] ?? "");
  }
}

describe("getDemoLogins", () => {
  it("lists an account only when both of its variables are set", () => {
    stub({});
    expect(getDemoLogins()).toEqual([]);
    stub({ DEMO_LOGIN_EMAIL: "demo@example.com" });
    expect(getDemoLogins()).toEqual([]);
  });

  it("reads the reviewer and the approver on every call", () => {
    stub({
      DEMO_LOGIN_EMAIL: "demo@example.com",
      DEMO_LOGIN_PASSWORD: PASSWORD,
    });
    expect(getDemoLogins()).toEqual([
      { role: "reviewer", email: "demo@example.com", password: PASSWORD },
    ]);
    stub({
      DEMO_LOGIN_EMAIL: "demo@example.com",
      DEMO_LOGIN_PASSWORD: PASSWORD,
      DEMO_APPROVER_EMAIL: "approver@example.com",
      DEMO_APPROVER_PASSWORD: APPROVER_PASSWORD,
    });
    expect(getDemoLogins().map((login) => login.role)).toEqual([
      "reviewer",
      "approver",
    ]);
  });
});

describe("DemoCredentials", () => {
  it("shows each account with its role", () => {
    render(
      <DemoCredentials
        logins={[
          { role: "reviewer", email: "demo@example.com", password: PASSWORD },
          {
            role: "approver",
            email: "approver@example.com",
            password: APPROVER_PASSWORD,
          },
        ]}
      />,
    );
    const box = screen.getByRole("region", { name: "Demo login" });
    for (const text of [
      "reviewer",
      "demo@example.com",
      PASSWORD,
      "approver@example.com",
      APPROVER_PASSWORD,
    ]) {
      expect(box.textContent).toContain(text);
    }
  });
});
