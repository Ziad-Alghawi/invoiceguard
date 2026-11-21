import { describe, expect, it } from "vitest";

import {
  type AuditEvent,
  canApprove,
  canReject,
  canReopen,
  canRequestOverride,
  confidencePercent,
  formatDateTime,
  isInvoiceId,
  isQueueFilter,
  overrideBlocker,
  overrideRequester,
  type User,
} from "@/lib/invoices";

describe("formatDateTime", () => {
  it("formats in the UI language and the company's time zone", () => {
    const iso = "2026-11-21T09:05:00Z";
    expect(formatDateTime(iso, "de")).toBe("21.11.2026, 10:05");
    expect(formatDateTime(iso, "en")).toBe("Nov 21, 2026, 10:05 AM");
  });
});

describe("confidencePercent", () => {
  it("shows LLM confidence as a percentage and nothing for XML", () => {
    expect(confidencePercent("0.550")).toBe("55 %");
    expect(confidencePercent("1.000")).toBe("100 %");
    expect(confidencePercent(null)).toBeNull();
  });
});

describe("decision rules", () => {
  it("match the API: approve ready, override blocked, reject any review status", () => {
    expect(canApprove("ready")).toBe(true);
    expect(canApprove("blocked")).toBe(false);
    expect(canApprove("override_requested")).toBe(false);
    expect(canApprove("approved")).toBe(false);
    expect(canRequestOverride("blocked")).toBe(true);
    expect(canRequestOverride("ready")).toBe(false);
    expect(canReject("failed")).toBe(true);
    expect(canReject("awaiting_extraction")).toBe(true);
    expect(canReject("override_requested")).toBe(true);
    expect(canReject("processing")).toBe(false);
    expect(canReject("rejected")).toBe(false);
  });

  it("reopen rejected invoices only, never approved ones", () => {
    expect(canReopen("rejected")).toBe(true);
    expect(canReopen("approved")).toBe(false);
    expect(canReopen("ready")).toBe(false);
  });
});

function event(action: string, actor: string): AuditEvent {
  return {
    id: 1,
    at: "2026-11-17T10:00:00Z",
    actor,
    action,
    status_before: null,
    status_after: null,
    reason: null,
    details: {},
  };
}

describe("four eyes", () => {
  const approver: User = {
    id: "1",
    email: "paul@example.com",
    display_name: "Paul",
    role: "approver",
  };

  it("finds the latest override requester in the history", () => {
    expect(overrideRequester([])).toBeNull();
    expect(
      overrideRequester([
        event("invoice.override_requested", "anna@example.com"),
        event("invoice.override_declined", "paul@example.com"),
        event("invoice.override_requested", "ida@example.com"),
      ]),
    ).toBe("ida@example.com");
  });

  it("lets only an approver who did not request it decide", () => {
    expect(overrideBlocker(approver, "anna@example.com")).toBeNull();
    expect(overrideBlocker(approver, "paul@example.com")).toBe("requester");
    expect(
      overrideBlocker({ ...approver, role: "reviewer" }, "anna@example.com"),
    ).toBe("role");
  });
});

describe("input checks", () => {
  it("accept only known queue filters", () => {
    expect(isQueueFilter("blocked")).toBe(true);
    expect(isQueueFilter("toString")).toBe(false);
    expect(isQueueFilter(["blocked"])).toBe(false);
  });

  it("accept only UUIDs as invoice IDs", () => {
    expect(isInvoiceId("6f1c2a52-8d0e-4c43-9a55-0c1f0f8a2b11")).toBe(true);
    expect(isInvoiceId("../auth/logout")).toBe(false);
  });
});
