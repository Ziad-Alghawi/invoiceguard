import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SecurityEventsTable } from "@/components/security-events-table";
import { describeEvent, type SecurityEvent } from "@/lib/security";
import { renderWithIntl } from "@/test/intl";

afterEach(cleanup);

function event(
  type: string,
  details: Record<string, unknown>,
  changes: Partial<SecurityEvent> = {},
): SecurityEvent {
  return {
    id: 1,
    at: "2026-11-17T10:00:00Z",
    type,
    severity: "low",
    invoice_id: null,
    user_id: null,
    user_email: null,
    details,
    ...changes,
  };
}

describe("describeEvent", () => {
  it("summarises each event type from its details", () => {
    expect(
      describeEvent(
        event("login_failed", { reason: "unknown_email", email: "x@y.z" }),
      ),
    ).toEqual({
      key: "loginFailedEmail",
      values: { reason: "unknown_email", email: "x@y.z" },
    });
    expect(describeEvent(event("login_failed", { reason: "locked" }))).toEqual({
      key: "loginFailed",
      values: { reason: "locked" },
    });
    expect(
      describeEvent(
        event("forbidden", {
          method: "POST",
          path: "/invoices/1/override/confirm",
          role: "reviewer",
          required_role: "approver",
        }),
      ),
    ).toEqual({
      key: "forbidden",
      values: {
        method: "POST",
        path: "/invoices/1/override/confirm",
        required: "approver",
        role: "reviewer",
      },
    });
    expect(
      describeEvent(
        event("injection_suspected", {
          findings: [
            { rule: "ignore_instructions" },
            { rule: "concealment" },
            { rule: "ignore_instructions" },
            "not a finding",
          ],
        }),
      ),
    ).toEqual({
      key: "injection",
      values: { rules: "ignore_instructions, concealment" },
    });
    expect(
      describeEvent(event("login_rate_limited", { email: "x@y.z" })),
    ).toEqual({ key: "loginRateLimited", values: { email: "x@y.z" } });
    expect(describeEvent(event("something_new", {}))).toBeNull();
  });
});

describe("SecurityEventsTable", () => {
  it("lists events with severity, user and a link to the invoice", () => {
    renderWithIntl(
      <SecurityEventsTable
        events={[
          event(
            "self_approval_attempt",
            { action: "confirm_override" },
            {
              severity: "high",
              user_email: "paul@example.com",
              invoice_id: "6f1c2a52-8d0e-4c43-9a55-0c1f0f8a2b11",
            },
          ),
        ]}
      />,
    );

    expect(screen.getByText("high")).toBeTruthy();
    expect(screen.getByText("paul@example.com")).toBeTruthy();
    expect(
      screen.getByText(
        "Tried to decide their own override request (confirm_override)",
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open invoice" }).getAttribute("href"),
    ).toBe("/invoices/6f1c2a52-8d0e-4c43-9a55-0c1f0f8a2b11");
  });

  it("renders attacker text as text, not markup", () => {
    const { container } = renderWithIntl(
      <SecurityEventsTable
        events={[
          event("login_failed", {
            reason: "unknown_email",
            email: "<img src=x onerror=alert(1)>",
          }),
        ]}
      />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("shows labels in German and an unknown type as the API sent it", () => {
    renderWithIntl(
      <SecurityEventsTable
        events={[
          event("forbidden", {
            method: "POST",
            path: "/invoices/1/override/confirm",
            role: "reviewer",
            required_role: "approver",
          }),
          event("something_new", {}, { id: 2, severity: "medium" }),
        ]}
      />,
      { locale: "de" },
    );

    expect(screen.getByText("Rollenprüfung verweigert")).toBeTruthy();
    expect(
      screen.getByText(
        "POST /invoices/1/override/confirm erfordert die Rolle approver (Benutzer hat reviewer)",
      ),
    ).toBeTruthy();
    expect(screen.getByText("niedrig")).toBeTruthy();
    expect(screen.getByText("something_new")).toBeTruthy();
    expect(screen.getByText("mittel")).toBeTruthy();
  });

  it("says so when there is nothing yet", () => {
    renderWithIntl(<SecurityEventsTable events={[]} />);
    expect(screen.getByText("No security events yet.")).toBeTruthy();
  });
});
