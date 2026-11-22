/**
 * The codes the API sends that the UI shows with a label per language (messages/*.json, "Codes").
 * codes.test.ts checks these lists against the API's source, so a new code there fails the web
 * tests until it has a label. A code the UI does not know is shown as it is.
 */

import type { AgentRunStatus } from "@/lib/investigations";
import type { CheckStatus, InvoiceStatus, Role } from "@/lib/invoices";
import type { Severity } from "@/lib/security";

export const INVOICE_STATUSES = [
  "received",
  "processing",
  "awaiting_extraction",
  "ready",
  "blocked",
  "failed",
  "override_requested",
  "approved",
  "rejected",
] as const satisfies readonly InvoiceStatus[];

export const CHECK_STATUSES = [
  "passed",
  "warning",
  "failed",
  "skipped",
] as const satisfies readonly CheckStatus[];

export const ROLES = [
  "reviewer",
  "approver",
] as const satisfies readonly Role[];

export const SEVERITIES = [
  "low",
  "medium",
  "high",
] as const satisfies readonly Severity[];

export const AGENT_RUN_STATUSES = [
  "running",
  "completed",
  "stopped",
  "failed",
] as const satisfies readonly AgentRunStatus[];

/** `CHECK_TYPE` of each module in the API's checks package. */
export const CHECK_TYPES = [
  "duplicate",
  "iban",
  "kosit",
  "low_confidence",
  "po_match",
  "prompt_injection",
  "supplier_known",
  "vat_math",
] as const;

/** The audit log's actions (`audit_events.action`). */
export const AUDIT_ACTIONS = [
  "auth.locked",
  "auth.login",
  "auth.login_failed",
  "auth.logout",
  "demo.reset",
  "invoice.approved",
  "invoice.exported",
  "invoice.extraction_deferred",
  "invoice.override_confirmed",
  "invoice.override_declined",
  "invoice.override_requested",
  "invoice.received",
  "invoice.rejected",
  "invoice.reopened",
  "invoice.status_changed",
  "user.created",
  "user.updated",
] as const;

/** The security log's event types (the API's security.py). */
export const SECURITY_EVENT_TYPES = [
  "account_locked",
  "forbidden",
  "injection_suspected",
  "login_failed",
  "login_rate_limited",
  "self_approval_attempt",
] as const;

/** EN 16931 business terms by the API's field name (parsing/fields.py). */
export const FIELD_NAMES = [
  "invoice_number",
  "issue_date",
  "type_code",
  "currency",
  "due_date",
  "seller_name",
  "seller_vat_id",
  "buyer_name",
  "buyer_vat_id",
  "payee_iban",
  "order_reference",
  "line_total",
  "allowance_total",
  "charge_total",
  "net_total",
  "tax_total",
  "gross_total",
  "amount_due",
  "line_id",
  "quantity",
  "unit_code",
  "net_amount",
  "net_price",
  "vat_rate",
  "item_name",
] as const;

/** Codes of the status reasons processing writes (the API's status_reasons.py). */
export const REASON_CODES = [
  "failed_checks",
  "awaiting_extraction",
  "extraction_off",
  "daily_budget",
  "internal_error",
  "restarted",
] as const;

export type CheckType = (typeof CHECK_TYPES)[number];
export type ReasonCode = (typeof REASON_CODES)[number];
export type AuditAction = (typeof AUDIT_ACTIONS)[number];
export type SecurityEventType = (typeof SECURITY_EVENT_TYPES)[number];
export type FieldName = (typeof FIELD_NAMES)[number];

function isOneOf<T extends string>(
  list: readonly T[],
  value: string,
): value is T {
  return list.some((item) => item === value);
}

export function isInvoiceStatus(value: string): value is InvoiceStatus {
  return isOneOf(INVOICE_STATUSES, value);
}

export function isReasonCode(value: string): value is ReasonCode {
  return isOneOf(REASON_CODES, value);
}

export function isCheckType(value: string): value is CheckType {
  return isOneOf(CHECK_TYPES, value);
}

export function isAuditAction(value: string): value is AuditAction {
  return isOneOf(AUDIT_ACTIONS, value);
}

export function isSecurityEventType(value: string): value is SecurityEventType {
  return isOneOf(SECURITY_EVENT_TYPES, value);
}

export function isFieldName(value: string): value is FieldName {
  return isOneOf(FIELD_NAMES, value);
}
