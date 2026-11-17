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

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * One line about the event from its details. Details can hold attacker-chosen text (a typed
 * email, a snippet from an invoice); React renders it as text, never as markup.
 */
export function describeEvent(event: SecurityEvent): string {
  const details = event.details;
  switch (event.type) {
    case "login_failed": {
      const email = text(details.email);
      return `Failed login (${text(details.reason)})${email ? `: ${email}` : ""}`;
    }
    case "account_locked":
      return `Account locked: ${text(details.reason)}`;
    case "forbidden":
      return `${text(details.method)} ${text(details.path)} needs the ${text(details.required_role)} role (user is ${text(details.role)})`;
    case "self_approval_attempt":
      return `Tried to decide their own override request (${text(details.action)})`;
    case "injection_suspected": {
      const findings = Array.isArray(details.findings) ? details.findings : [];
      const rules = findings
        .map((finding: unknown) =>
          typeof finding === "object" && finding !== null && "rule" in finding
            ? text(finding.rule)
            : "",
        )
        .filter(Boolean);
      return `Prompt injection suspected in the invoice text: ${[...new Set(rules)].join(", ")}`;
    }
    default:
      return event.type;
  }
}
