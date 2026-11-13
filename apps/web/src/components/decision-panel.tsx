"use client";

import { useActionState } from "react";

import type { ActionState } from "@/app/actions";
import { canApprove, canReject, type InvoiceStatus } from "@/lib/invoices";

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

const INITIAL: ActionState = { error: null };
const BUTTON =
  "inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium disabled:opacity-50";
const TEXTAREA = "w-full rounded-md border bg-background p-2 text-sm";

function ErrorText({ state }: { state: ActionState }) {
  return state.error ? (
    <p role="alert" className="text-sm text-destructive">
      {state.error}
    </p>
  ) : null;
}

/**
 * Approve and reject forms. A blocked invoice needs an override reason and a confirmation;
 * the API enforces the same rules (ADR-012), this only guides the reviewer.
 */
export function DecisionPanel({
  status,
  failedChecks,
  approve,
  reject,
}: {
  status: InvoiceStatus;
  failedChecks: string[];
  approve: Action;
  reject: Action;
}) {
  const [approveState, approveAction, approving] = useActionState(
    approve,
    INITIAL,
  );
  const [rejectState, rejectAction, rejecting] = useActionState(
    reject,
    INITIAL,
  );
  const busy = approving || rejecting;

  if (!canApprove(status) && !canReject(status)) {
    return (
      <p className="text-sm text-muted-foreground">
        No decision possible while the invoice is {status.replace("_", " ")}.
      </p>
    );
  }
  const blocked = status === "blocked";

  return (
    <div className="flex flex-col gap-4">
      {canApprove(status) && (
        <form
          action={approveAction}
          aria-label="Approve"
          className="flex flex-col gap-2"
        >
          {blocked && (
            <>
              <p className="text-sm text-destructive">
                Blocked by failed checks: {failedChecks.join(", ")}. Approving
                overrides them and needs a reason.
              </p>
              <label className="flex flex-col gap-1 text-sm">
                Override reason
                <textarea
                  name="override_reason"
                  required
                  maxLength={2000}
                  rows={3}
                  className={TEXTAREA}
                />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" name="confirm" required />I checked the
                failed checks and approve anyway.
              </label>
            </>
          )}
          <button
            type="submit"
            disabled={busy}
            className={`${BUTTON} ${blocked ? "bg-destructive text-white" : "bg-primary text-primary-foreground"}`}
          >
            {blocked ? "Approve with override" : "Approve"}
          </button>
          <ErrorText state={approveState} />
        </form>
      )}
      {canReject(status) && (
        <form
          action={rejectAction}
          aria-label="Reject"
          className="flex flex-col gap-2"
        >
          <label className="flex flex-col gap-1 text-sm">
            Reject reason
            <textarea
              name="reason"
              required
              maxLength={2000}
              rows={3}
              className={TEXTAREA}
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className={`${BUTTON} border bg-background`}
          >
            Reject
          </button>
          <ErrorText state={rejectState} />
        </form>
      )}
    </div>
  );
}
