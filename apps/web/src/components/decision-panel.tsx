"use client";

import { useTranslations } from "next-intl";
import { useActionState } from "react";

import type { ActionState } from "@/app/actions";
import { useCheckTypeLabel } from "@/components/check-list";
import {
  accountField,
  type Bookings,
  preselected,
  suggestionNote,
} from "@/lib/bookings";
import {
  canApprove,
  canReject,
  canReopen,
  canRequestOverride,
  type InvoiceStatus,
  type OverrideBlocker,
} from "@/lib/invoices";

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

export type DecisionActions = {
  approve: Action;
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
  blocker: OverrideBlocker | null;
};

const INITIAL: ActionState = { error: null };
const BUTTON =
  "inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium disabled:opacity-50";
const PRIMARY = `${BUTTON} bg-primary text-primary-foreground`;
const DANGER = `${BUTTON} bg-destructive text-white`;
const OUTLINE = `${BUTTON} border bg-background`;
const TEXTAREA = "w-full rounded-md border bg-background p-2 text-sm";
const SELECT = "h-9 w-full rounded-md border bg-background px-2 text-sm";

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
 * One SKR03 account per line, preselected with the booking suggestion (ADR-020). Only a
 * suggestion: the person approving chooses, and the choice is stored with the decision.
 */
function AccountFields({ bookings }: { bookings: Bookings }) {
  const t = useTranslations("Decision");
  if (bookings.lines.length === 0) {
    return null;
  }
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 text-sm font-medium">{t("accounts")}</legend>
      {bookings.lines.map((line) => {
        const note = suggestionNote(line, t("imported"));
        return (
          <label key={line.line_no} className="flex flex-col gap-1 text-sm">
            <span>
              {t("accountLine", { line: line.line_no, text: line.text })}
            </span>
            <select
              name={accountField(line.line_no)}
              defaultValue={preselected(line, bookings.default_account)}
              className={SELECT}
            >
              {bookings.accounts.map((account) => (
                <option key={account.number} value={account.number}>
                  {t("account", { number: account.number, name: account.name })}
                </option>
              ))}
            </select>
            <span className="text-xs text-muted-foreground">
              {note === null ? t("noSuggestion") : t("suggested", note)}
            </span>
          </label>
        );
      })}
    </fieldset>
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
  bookings,
  actions,
}: {
  status: InvoiceStatus;
  failedChecks: string[];
  override: OverrideRequest;
  bookings: Bookings;
  actions: DecisionActions;
}) {
  const t = useTranslations("Decision");
  const statuses = useTranslations("Codes.invoiceStatus");
  const checkType = useCheckTypeLabel();
  const checks = failedChecks.map(checkType).join(", ");
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
          {t("noDecision", { status: statuses(status) })}
        </p>
        {canReopen(status) && (
          <form
            action={reopenAction}
            aria-label={t("reopenForm")}
            className="flex flex-col gap-2"
          >
            <p className="text-sm">{t("reopenIntro")}</p>
            <ReasonField label={t("reopenReason")} name="reopen_reason" />
            <button type="submit" disabled={busy} className={OUTLINE}>
              {t("reopen")}
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
        <form
          action={approveAction}
          aria-label={t("approve")}
          className="flex flex-col gap-3"
        >
          <AccountFields bookings={bookings} />
          <button type="submit" disabled={busy} className={PRIMARY}>
            {t("approve")}
          </button>
          <ErrorText state={approveState} />
        </form>
      )}
      {canRequestOverride(status) && (
        <form
          action={requestAction}
          aria-label={t("requestForm")}
          className="flex flex-col gap-2"
        >
          <p className="text-sm text-destructive">
            {t("blockedBy", { checks })}
          </p>
          <ReasonField label={t("overrideReason")} name="override_reason" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="confirm" required />
            {t("confirmChecked")}
          </label>
          <button type="submit" disabled={busy} className={DANGER}>
            {t("requestOverride")}
          </button>
          <ErrorText state={requestState} />
        </form>
      )}
      {overrideRequested && (
        <div className="flex flex-col gap-2">
          <p className="text-sm">
            {t("overrideRequested", {
              requester: override.requestedBy ?? t("anotherUser"),
              checks,
            })}
          </p>
          {override.blocker === null ? (
            <form aria-label={t("decideForm")} className="flex flex-col gap-2">
              <AccountFields bookings={bookings} />
              <ReasonField label={t("approverReason")} name="approver_reason" />
              <div className="flex flex-wrap gap-2">
                <button
                  type="submit"
                  formAction={confirmAction}
                  disabled={busy}
                  className={DANGER}
                >
                  {t("confirmOverride")}
                </button>
                <button
                  type="submit"
                  formAction={declineAction}
                  disabled={busy}
                  className={OUTLINE}
                >
                  {t("declineOverride")}
                </button>
              </div>
              <ErrorText state={confirmState} />
              <ErrorText state={declineState} />
            </form>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t(
                override.blocker === "role"
                  ? "blockerRole"
                  : "blockerRequester",
              )}
            </p>
          )}
        </div>
      )}
      {canReject(status) && (
        <form
          action={rejectAction}
          aria-label={t("rejectForm")}
          className="flex flex-col gap-2"
        >
          <ReasonField label={t("rejectReason")} name="reason" />
          <button type="submit" disabled={busy} className={OUTLINE}>
            {t("reject")}
          </button>
          <ErrorText state={rejectState} />
        </form>
      )}
    </div>
  );
}
