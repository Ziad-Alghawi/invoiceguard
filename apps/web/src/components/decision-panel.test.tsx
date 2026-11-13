import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ActionState } from "@/app/actions";
import { DecisionPanel } from "@/components/decision-panel";

afterEach(cleanup);

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

function actions() {
  return {
    approve: vi.fn<Action>().mockResolvedValue({ error: null }),
    reject: vi.fn<Action>().mockResolvedValue({ error: null }),
  };
}

describe("DecisionPanel", () => {
  it("offers a plain approve for a ready invoice", () => {
    render(<DecisionPanel status="ready" failedChecks={[]} {...actions()} />);

    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.queryByLabelText("Override reason")).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
  });

  it("asks for an override reason and confirmation on a blocked invoice", () => {
    render(
      <DecisionPanel status="blocked" failedChecks={["iban"]} {...actions()} />,
    );

    expect(screen.getByText(/Blocked by failed checks: iban\./)).toBeTruthy();
    const reason =
      screen.getByLabelText<HTMLTextAreaElement>("Override reason");
    expect(reason.required).toBe(true);
    const confirm = screen.getByRole<HTMLInputElement>("checkbox");
    expect(confirm.required).toBe(true);
    expect(
      screen.getByRole("button", { name: "Approve with override" }),
    ).toBeTruthy();
  });

  it("sends the reject reason and shows the API's refusal", async () => {
    const { approve, reject } = actions();
    reject.mockResolvedValue({ error: "The invoice is approved; ..." });
    render(
      <DecisionPanel
        status="ready"
        failedChecks={[]}
        approve={approve}
        reject={reject}
      />,
    );

    fireEvent.change(screen.getByLabelText("Reject reason"), {
      target: { value: "Duplicate of 2026-IT-0814" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "The invoice is approved; ...",
    );
    expect(reject).toHaveBeenCalledOnce();
    const formData = reject.mock.calls[0][1];
    expect(formData.get("reason")).toBe("Duplicate of 2026-IT-0814");
    expect(approve).not.toHaveBeenCalled();
  });

  it("offers only reject for a failed invoice and nothing after a decision", () => {
    const { rerender } = render(
      <DecisionPanel status="failed" failedChecks={[]} {...actions()} />,
    );
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();

    rerender(
      <DecisionPanel status="approved" failedChecks={[]} {...actions()} />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.getByText("No decision possible while the invoice is approved."),
    ).toBeTruthy();
  });
});
