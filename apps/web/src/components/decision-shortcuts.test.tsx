import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { ActionState } from "@/app/actions";
import { DecisionPanel } from "@/components/decision-panel";
import type { InvoiceStatus } from "@/lib/invoices";
import { renderWithIntl } from "@/test/intl";

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

beforeAll(() => {
  HTMLElement.prototype.scrollIntoView = () => undefined;
  // jsdom has <dialog> without the modal methods; open and close it as a browser would.
  HTMLDialogElement.prototype.showModal ??= function showModal(
    this: HTMLDialogElement,
  ) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(
    this: HTMLDialogElement,
  ) {
    this.removeAttribute("open");
  };
});

afterEach(cleanup);

function panel(status: InvoiceStatus) {
  const done = { error: null };
  const calls = {
    approve: vi.fn<Action>().mockResolvedValue(done),
    reject: vi.fn<Action>().mockResolvedValue(done),
    requestOverride: vi.fn<Action>().mockResolvedValue(done),
    confirmOverride: vi.fn<Action>().mockResolvedValue(done),
    declineOverride: vi.fn<Action>().mockResolvedValue(done),
    reopen: vi.fn<Action>().mockResolvedValue(done),
  };
  renderWithIntl(
    <DecisionPanel
      status={status}
      failedChecks={status === "ready" ? [] : ["iban"]}
      override={{ requestedBy: null, blocker: null }}
      bookings={{ accounts: [], default_account: "4900", lines: [] }}
      actions={calls}
    />,
    { locale: "de" },
  );
  return calls;
}

function press(key: string, target: Element = document.body) {
  fireEvent.keyDown(target, { key });
}

function confirmDialog() {
  return document.querySelector("dialog") as HTMLDialogElement;
}

describe("DecisionPanel shortcuts", () => {
  it("a asks first, and approves only after the confirmation", async () => {
    const calls = panel("ready");
    press("a");
    expect(confirmDialog().open).toBe(true);
    expect(screen.getByText("Diese Rechnung freigeben?")).toBeTruthy();
    // Enter confirms: the confirm button has the focus, not cancel.
    expect(document.activeElement?.textContent).toBe("Freigeben");
    expect(calls.approve).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(
        screen
          .getAllByRole("button", { name: "Freigeben", hidden: true })
          .at(-1)!,
      );
    });
    expect(confirmDialog().open).toBe(false);
    await waitFor(() => expect(calls.approve).toHaveBeenCalledTimes(1));
  });

  it("cancel closes the confirmation without approving", () => {
    const calls = panel("ready");
    press("a");
    fireEvent.click(
      screen.getByRole("button", { name: "Abbrechen", hidden: true }),
    );
    expect(confirmDialog().open).toBe(false);
    expect(calls.approve).not.toHaveBeenCalled();
  });

  it("r goes to the reject reason; nothing is rejected without one", () => {
    const calls = panel("ready");
    press("r");
    expect(document.activeElement).toBe(
      screen.getByLabelText("Grund der Ablehnung"),
    );
    expect(calls.reject).not.toHaveBeenCalled();
  });

  it("never fires while typing in a text field", () => {
    panel("ready");
    const reason = screen.getByLabelText("Grund der Ablehnung");
    reason.focus();
    press("a", reason);
    expect(confirmDialog().open).toBe(false);
  });

  it("a does nothing on a blocked invoice, which needs the four-eyes override", () => {
    panel("blocked");
    press("a");
    expect(document.querySelector("dialog")).toBeNull();
  });
});
