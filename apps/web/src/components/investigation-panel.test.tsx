import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ActionState } from "@/app/actions";
import { InvestigationPanel } from "@/components/investigation-panel";
import type { Investigation } from "@/lib/investigations";
import { RUN } from "@/lib/investigations.fixture";
import { renderWithIntl } from "@/test/intl";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  refresh.mockClear();
});

function panel(
  investigation: Investigation,
  investigate = vi
    .fn<() => Promise<ActionState>>()
    .mockResolvedValue({ error: null }),
) {
  renderWithIntl(
    <InvestigationPanel
      investigation={investigation}
      investigate={investigate}
    />,
  );
  return investigate;
}

const READY: Investigation = {
  run: null,
  mode: "live",
  can_investigate: true,
  reason: null,
};

describe("InvestigationPanel", () => {
  it("offers to investigate a blocked invoice", () => {
    const investigate = panel(READY);

    fireEvent.click(screen.getByRole("button", { name: "Investigate" }));

    expect(investigate).toHaveBeenCalled();
  });

  it("shows the finding, the German email draft and every step", () => {
    panel({ ...READY, run: RUN });

    expect(
      screen.getByText("The IBAN is not registered to any supplier."),
    ).toBeTruthy();
    expect(screen.getByText(/Subject: Rückfrage zu Rechnung/)).toBeTruthy();
    expect(
      screen.getByText("2 steps: model calls and tool calls"),
    ).toBeTruthy();
    expect(screen.getByText("check_iban(DE58876543210000000099)")).toBeTruthy();
    expect(screen.getByText(/\$0\.006008 · 12\.1 s/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Investigate again" }),
    ).toBeTruthy();
  });

  it("labels a recorded run as recorded", () => {
    panel({
      ...READY,
      mode: "recorded",
      run: { ...RUN, source: "recorded", recorded_at: "2026-11-18T00:29:38Z" },
    });

    expect(screen.getByText(/recorded run from/)).toBeTruthy();
  });

  it("explains why an invoice is not investigated", () => {
    panel({
      run: null,
      mode: "live",
      can_investigate: false,
      reason:
        "Not investigated: the invoice text looks like a prompt injection.",
    });

    expect(screen.queryByRole("button", { name: "Investigate" })).toBeNull();
    expect(screen.getByText(/looks like a prompt injection/)).toBeTruthy();
  });

  it("shows why a run stopped, without an email", () => {
    panel({
      ...READY,
      run: {
        ...RUN,
        status: "stopped",
        stop_reason: "cost_cap",
        error: "The agent reached the cost cap for this invoice.",
        finding: null,
        email_subject: null,
        email_body: null,
      },
    });

    expect(screen.getByRole("status").textContent).toContain("cost cap");
    expect(screen.queryByText(/Email draft/)).toBeNull();
  });

  it("reloads the page while a run is going on", () => {
    vi.useFakeTimers();
    panel({
      ...READY,
      can_investigate: false,
      reason: "An investigation of this invoice is already running.",
      run: { ...RUN, status: "running", finding: null },
    });

    vi.advanceTimersByTime(4100);

    expect(refresh).toHaveBeenCalledTimes(2);
    expect(screen.getByText("The agent is investigating…")).toBeTruthy();
    expect(screen.queryByText(/already running/)).toBeNull();
  });
});
