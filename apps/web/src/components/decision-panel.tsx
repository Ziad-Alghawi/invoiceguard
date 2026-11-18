"use client";

import { useActionState } from "react";

import type { ActionState } from "@/app/actions";
import {
  canApprove,
  canReject,
  canReopen,
  canRequestOverride,
  type InvoiceStatus,
} from "@/lib/invoices";

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

export type DecisionActions = {
  approve: () => Promise<ActionState>;
  reject: Action;
  requestOverride: Action;
  confirmOverride: Action;
  declineOverride: Action;
  reopen: Action;
};

export type OverrideRequest = {
  /** Email of the user who requested it. */
  requestedBy: string | null;
  /** Why this user cannot confirm or decline it; null when they can. */
  blocker: string | null;
};

const INITIAL: ActionState = { error: null };
const BUTTON =
  "inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium disabled:opacity-50";
const PRIMARY = `${BUTTON} bg-primary text-primary-foreground`;
const DANGER = `${BUTTON} bg-destructive text-white`;
const OUTLINE = `${BUTTON} border bg-background`;
const TEXTAREA = "w-full rounded-md border bg-background p-2 text-sm";

function ErrorText({ state }: { state: ActionState }) {
  return state.error ? (
    <p role="alert" className="text-sm text-destructive">
      {state.error}
    </p>
  ) : null;
}

function ReasonField({ label, name }: { label: string; name: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <textarea
        name={name}
        required
        maxLength={2000}
        rows={3}
        className={TEXTAREA}
      />
    </label>
  );
}

/**
 * The decisions the user can make on the invoice. A ready invoice is approved by one person; a
 * blocked one needs a four-eyes override: a reason from one user, then a confirmation by a
 * different user with the approver role (ADR-016). The API enforces the same rules; this only
 * guides the user.
 */
export function DecisionPanel({
  status,
  failedChecks,
  override,
  actions,
}: {
  status: InvoiceStatus;
  failedChecks: string[];
  override: OverrideRequest;
  actions: DecisionActions;
}) {
  const [approveState, approveAction, approving] = useActionState(
    actions.approve,
    INITIAL,
  );
  const [requestState, requestAction, requesting] = useActionState(
    actions.requestOverride,
    INITIAL,
  );
  const [confirmState, confirmAction, confirming] = useActionState(
    actions.confirmOverride,
    INITIAL,
  );
  const [declineState, declineAction, declining] = useActionState(
    actions.declineOverride,
    INITIAL,
  );
  const [rejectState, rejectAction, rejecting] = useActionState(
    actions.reject,
    INITIAL,
  );
  const [reopenState, reopenAction, reopening] = useActionState(
    actions.reopen,
    INITIAL,
  );
  const busy =
    approving ||
    requesting ||
    confirming ||
    declining ||
    rejecting ||
    reopening;
  const overrideRequested = status === "override_requested";

  if (!canApprove(status) && !canReject(status)) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          No decision possible while the invoice is {status.replace("_", " ")}.
        </p>
        {canReopen(status) && (
          <form
            action={reopenAction}
            aria-label="Reopen"
            className="flex flex-col gap-2"
          >
            <p className="text-sm">
              Rejected by mistake? Reopen it: the checks run again on the
              current master data, and it waits for review.
            </p>
            <ReasonField label="Reopen reason" name="reopen_reason" />
            <button type="submit" disabled={busy} className={OUTLINE}>
              Reopen
            </button>
            <ErrorText state={reopenState} />
          </form>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {canApprove(status) && (
        <form action={approveAction} aria-label="Approve">
          <button type="submit" disabled={busy} className={PRIMARY}>
            Approve
          </button>
          <ErrorText state={approveState} />
        </form>
      )}
      {canRequestOverride(status) && (
        <form
          action={requestAction}
          aria-label="Request override"
          className="flex flex-col gap-2"
        >
          <p className="text-sm text-destructive">
            Blocked by failed checks: {failedChecks.join(", ")}. Approving it
            needs an override: your reason, then a confirmation by a second
            person with the approver role.
          </p>
          <ReasonField label="Override reason" name="override_reason" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="confirm" required />I checked the
            failed checks and ask to approve anyway.
          </label>
          <button type="submit" disabled={busy} className={DANGER}>
            Request override
          </button>
          <ErrorText state={requestState} />
        </form>
      )}
      {overrideRequested && (
        <div className="flex flex-col gap-2">
          <p className="text-sm">
            Override requested by {override.requestedBy ?? "another user"} for
            the failed checks: {failedChecks.join(", ")}. It waits for a second
            person with the approver role.
          </p>
          {override.blocker === null ? (
            <form aria-label="Decide override" className="flex flex-col gap-2">
              <ReasonField label="Approver reason" name="approver_reason" />
              <div className="flex flex-wrap gap-2">
                <button
                  type="submit"
                  formAction={confirmAction}
                  disabled={busy}
                  className={DANGER}
                >
                  Confirm override
                </button>
                <button
                  type="submit"
                  formAction={declineAction}
                  disabled={busy}
                  className={OUTLINE}
                >
                  Decline override
                </button>
              </div>
              <ErrorText state={confirmState} />
              <ErrorText state={declineState} />
            </form>
          ) : (
            <p className="text-sm text-muted-foreground">{override.blocker}</p>
          )}
        </div>
      )}
      {canReject(status) && (
        <form
          action={rejectAction}
          aria-label="Reject"
          className="flex flex-col gap-2"
        >
          <ReasonField label="Reject reason" name="reason" />
          <button type="submit" disabled={busy} className={OUTLINE}>
            Reject
          </button>
          <ErrorText state={rejectState} />
        </form>
      )}
    </div>
  );
}
