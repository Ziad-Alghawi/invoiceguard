/** Security events (R2-4), as `GET /security-events` returns them to approvers. */

export type Severity = "low" | "medium" | "high";

export type SecurityEvent = {
  id: number;
  at: string;
  type: string;
  severity: Severity;
  invoice_id: string | null;
  user_id: string | null;
  user_email: string | null;
  details: Record<string, unknown>;
};

/** One line about an event: a message key in "Security.describe" and its values. */
export type EventDescription = {
  key:
    | "loginFailed"
    | "loginFailedEmail"
    | "accountLocked"
    | "loginRateLimited"
    | "forbidden"
    | "selfApproval"
    | "injection";
  values: Record<string, string>;
};

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * One line about the event from its details, or null for a type without one. Details can hold
 * attacker-chosen text (a typed email, a snippet from an invoice); React renders it as text,
 * never as markup.
 */
export function describeEvent(event: SecurityEvent): EventDescription | null {
  const details = event.details;
  switch (event.type) {
    case "login_failed": {
      const email = text(details.email);
      const reason = text(details.reason);
      return email
        ? { key: "loginFailedEmail", values: { reason, email } }
        : { key: "loginFailed", values: { reason } };
    }
    case "account_locked":
      return { key: "accountLocked", values: { reason: text(details.reason) } };
    case "login_rate_limited":
      return {
        key: "loginRateLimited",
        values: { email: text(details.email) },
      };
    case "forbidden":
      return {
        key: "forbidden",
        values: {
          method: text(details.method),
          path: text(details.path),
          required: text(details.required_role),
          role: text(details.role),
        },
      };
    case "self_approval_attempt":
      return { key: "selfApproval", values: { action: text(details.action) } };
    case "injection_suspected": {
      const findings = Array.isArray(details.findings) ? details.findings : [];
      const rules = findings
        .map((finding: unknown) =>
          typeof finding === "object" && finding !== null && "rule" in finding
            ? text(finding.rule)
            : "",
        )
        .filter(Boolean);
      return {
        key: "injection",
        values: { rules: [...new Set(rules)].join(", ") },
      };
    }
    default:
      return null;
  }
}
