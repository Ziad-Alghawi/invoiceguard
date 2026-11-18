/** Shapes of the InvoiceGuard API responses the review UI reads, and helpers for them. */

export type InvoiceStatus =
  | "received"
  | "processing"
  | "awaiting_extraction"
  | "ready"
  | "blocked"
  | "failed"
  | "override_requested"
  | "approved"
  | "rejected";

export type CheckStatus = "passed" | "warning" | "failed" | "skipped";

export type Invoice = {
  id: string;
  status: InvoiceStatus;
  status_reason: string | null;
  source_type: "xml" | "pdf";
  original_filename: string;
  sha256: string;
  size_bytes: number;
  created_at: string;
};

export type InvoiceField = {
  code: string;
  name: string;
  line_no: number | null;
  value: string;
  source: "xml" | "llm";
  /** Decimal string such as "0.950"; null for values read from XML. */
  confidence: string | null;
  low_confidence: boolean;
  evidence: { page?: number; snippet?: string } | null;
};

export type InvoiceCheck = {
  type: string;
  status: CheckStatus;
  message: string;
  evidence: Record<string, unknown>;
  created_at: string;
};

export type InvoiceDetail = Invoice & {
  fields: InvoiceField[];
  checks: InvoiceCheck[];
  file_url: string;
  llm_calls: number;
  llm_cost_usd: string;
};

export type AuditEvent = {
  id: number;
  at: string;
  actor: string;
  action: string;
  status_before: string | null;
  status_after: string | null;
  reason: string | null;
  details: Record<string, unknown>;
};

export type Role = "reviewer" | "approver";

export type User = {
  id: string;
  email: string;
  display_name: string;
  role: Role;
};

/** The queue tabs: each is one or more statuses passed to `GET /invoices?status=`. */
export const QUEUE_FILTERS = {
  review: {
    label: "To review",
    statuses: ["ready", "blocked", "override_requested"],
  },
  blocked: { label: "Blocked", statuses: ["blocked"] },
  override: { label: "Override requested", statuses: ["override_requested"] },
  approved: { label: "Approved", statuses: ["approved"] },
  rejected: { label: "Rejected", statuses: ["rejected"] },
  other: {
    label: "Processing / failed",
    statuses: ["received", "processing", "awaiting_extraction", "failed"],
  },
  all: { label: "All", statuses: [] },
} as const satisfies Record<
  string,
  { label: string; statuses: readonly InvoiceStatus[] }
>;

export type QueueFilter = keyof typeof QUEUE_FILTERS;

export function isQueueFilter(value: unknown): value is QueueFilter {
  return typeof value === "string" && Object.hasOwn(QUEUE_FILTERS, value);
}

/** Decisions a user can make, as the API enforces them (ADR-016). */
export function canApprove(status: InvoiceStatus): boolean {
  return status === "ready";
}

/** A blocked invoice is approved only through a four-eyes override. */
export function canRequestOverride(status: InvoiceStatus): boolean {
  return status === "blocked";
}

export function canReject(status: InvoiceStatus): boolean {
  return (
    status === "ready" ||
    status === "blocked" ||
    status === "failed" ||
    status === "awaiting_extraction" ||
    status === "override_requested"
  );
}

/** Only a rejected invoice can be reopened; an approved one never (ADR-016). */
export function canReopen(status: InvoiceStatus): boolean {
  return status === "rejected";
}

/** The email of whoever made the latest override request, from the audit history. */
export function overrideRequester(history: AuditEvent[]): string | null {
  const requests = history.filter(
    (event) => event.action === "invoice.override_requested",
  );
  return requests.at(-1)?.actor ?? null;
}

/** Why the user cannot confirm or decline the override, or null when they can. */
export function overrideBlocker(
  user: User,
  requestedBy: string | null,
): string | null {
  if (user.role !== "approver") {
    return "Only a user with the approver role can confirm or decline it.";
  }
  if (requestedBy === user.email) {
    return "You requested it, so a different approver has to decide it.";
  }
  return null;
}

/** "payee_iban" → "Payee IBAN". */
export function fieldLabel(name: string): string {
  const words = name.split("_").map((word) => {
    const upper = word.toUpperCase();
    return ["IBAN", "VAT", "ID"].includes(upper)
      ? upper
      : word.charAt(0).toUpperCase() + word.slice(1);
  });
  return words.join(" ");
}

/** "0.550" → "55 %"; null (XML) → null. */
export function confidencePercent(confidence: string | null): string | null {
  if (confidence === null) {
    return null;
  }
  return `${Math.round(Number(confidence) * 100)} %`;
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Berlin",
  }).format(new Date(iso));
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Invoice IDs are UUIDs; checked before one is put into an API path. */
export function isInvoiceId(value: string): boolean {
  return UUID.test(value);
}
