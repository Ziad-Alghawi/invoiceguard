import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ActionState } from "@/app/actions";
import {
  DecisionPanel,
  type OverrideRequest,
} from "@/components/decision-panel";
import type { Bookings } from "@/lib/bookings";
import type { InvoiceStatus } from "@/lib/invoices";

afterEach(cleanup);

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

function actions() {
  const done = { error: null };
  return {
    approve: vi.fn<Action>().mockResolvedValue(done),
    reject: vi.fn<Action>().mockResolvedValue(done),
    requestOverride: vi.fn<Action>().mockResolvedValue(done),
    confirmOverride: vi.fn<Action>().mockResolvedValue(done),
    declineOverride: vi.fn<Action>().mockResolvedValue(done),
    reopen: vi.fn<Action>().mockResolvedValue(done),
  };
}

const NO_REQUEST: OverrideRequest = { requestedBy: null, blocker: null };
const BOOKINGS: Bookings = {
  accounts: [
    { number: "0410", name: "Geschäftsausstattung" },
    { number: "4806", name: "Wartungskosten für Hard- und Software" },
    { number: "4900", name: "Sonstige betriebliche Aufwendungen" },
  ],
  default_account: "4900",
  lines: [
    {
      line_no: 1,
      text: "Notebook 14 Zoll",
      method: "vector",
      suggestions: [
        {
          account: "0410",
          name: "Geschäftsausstattung",
          share: 0.9,
          sources: [],
        },
      ],
      booked: null,
    },
    {
      line_no: 2,
      text: "Neuer Artikel",
      method: "text",
      suggestions: [],
      booked: null,
    },
  ],
};
const OWN_REQUEST =
  "You requested it, so a different approver has to decide it.";

function panel(
  status: InvoiceStatus,
  override: OverrideRequest = NO_REQUEST,
  calls = actions(),
) {
  return render(
    <DecisionPanel
      status={status}
      failedChecks={status === "ready" ? [] : ["iban"]}
      override={override}
      bookings={BOOKINGS}
      actions={calls}
    />,
  );
}

describe("DecisionPanel", () => {
  it("offers a plain approve for a ready invoice", () => {
    panel("ready");

    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.queryByLabelText("Override reason")).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
  });

  it("approves with an account per line, preselected from the suggestion", async () => {
    const calls = actions();
    panel("ready", NO_REQUEST, calls);

    const first = screen.getByLabelText<HTMLSelectElement>(/1\. Notebook/);
    const second =
      screen.getByLabelText<HTMLSelectElement>(/2\. Neuer Artikel/);
    expect(first.value).toBe("0410");
    expect(second.value).toBe("4900");
    expect(screen.getByText(/No suggestion/)).toBeTruthy();
    fireEvent.change(second, { target: { value: "4806" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await vi.waitFor(() => expect(calls.approve).toHaveBeenCalledOnce());
    const formData = calls.approve.mock.calls[0][1];
    expect(formData.get("account-1")).toBe("0410");
    expect(formData.get("account-2")).toBe("4806");
  });

  it("offers an override request, not an approval, on a blocked invoice", () => {
    panel("blocked");

    expect(screen.getByText(/Blocked by failed checks: iban\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    const reason =
      screen.getByLabelText<HTMLTextAreaElement>("Override reason");
    expect(reason.required).toBe(true);
    expect(screen.getByRole<HTMLInputElement>("checkbox").required).toBe(true);
    expect(
      screen.getByRole("button", { name: "Request override" }),
    ).toBeTruthy();
  });

  it("lets an approver confirm or decline someone else's request", async () => {
    const calls = actions();
    panel(
      "override_requested",
      { requestedBy: "anna@example.com", blocker: null },
      calls,
    );

    expect(
      screen.getByText(/Override requested by anna@example\.com/),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Decline override" }),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Approver reason"), {
      target: { value: "Call notes checked." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm override" }));

    await vi.waitFor(() =>
      expect(calls.confirmOverride).toHaveBeenCalledOnce(),
    );
    const formData = calls.confirmOverride.mock.calls[0][1];
    expect(formData.get("approver_reason")).toBe("Call notes checked.");
    expect(formData.get("account-1")).toBe("0410");
    expect(calls.declineOverride).not.toHaveBeenCalled();
  });

  it("tells the requester or a reviewer why they cannot decide it", () => {
    panel("override_requested", {
      requestedBy: "anna@example.com",
      blocker: OWN_REQUEST,
    });

    expect(screen.getByText(OWN_REQUEST)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /override/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
  });

  it("sends the reject reason and shows the API's refusal", async () => {
    const calls = actions();
    calls.reject.mockResolvedValue({ error: "The invoice is approved; ..." });
    panel("ready", NO_REQUEST, calls);

    fireEvent.change(screen.getByLabelText("Reject reason"), {
      target: { value: "Duplicate of 2026-IT-0814" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "The invoice is approved; ...",
    );
    expect(calls.reject).toHaveBeenCalledOnce();
    expect(calls.reject.mock.calls[0][1].get("reason")).toBe(
      "Duplicate of 2026-IT-0814",
    );
    expect(calls.approve).not.toHaveBeenCalled();
  });

  it("offers only reject for a failed invoice and nothing after a decision", () => {
    const { rerender } = panel("failed");
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();

    rerender(
      <DecisionPanel
        status="approved"
        failedChecks={[]}
        override={NO_REQUEST}
        bookings={BOOKINGS}
        actions={actions()}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.getByText("No decision possible while the invoice is approved."),
    ).toBeTruthy();
  });

  it("offers reopen with a reason on a rejected invoice only", async () => {
    const calls = actions();
    panel("rejected", NO_REQUEST, calls);

    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    const reason = screen.getByLabelText<HTMLTextAreaElement>("Reopen reason");
    expect(reason.required).toBe(true);
    fireEvent.change(reason, { target: { value: "Rejected by mistake." } });
    fireEvent.click(screen.getByRole("button", { name: "Reopen" }));

    await vi.waitFor(() => expect(calls.reopen).toHaveBeenCalledTimes(1));
    expect(calls.reopen.mock.calls[0][1].get("reopen_reason")).toBe(
      "Rejected by mistake.",
    );
  });
});
