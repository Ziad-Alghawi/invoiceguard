"use server";

import { refresh } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { isLocale, LOCALE_COOKIE, LOCALE_COOKIE_MAX_AGE } from "@/i18n/config";
import { apiFetch, apiPostAnonymous, errorMessage } from "@/lib/api";
import { type BookingChoice, bookingsFromForm } from "@/lib/bookings";
import type { ExportState } from "@/lib/exports";
import { type Invoice, type InvoiceStatus, isInvoiceId } from "@/lib/invoices";
import { parseSessionCookie, SESSION_COOKIE } from "@/lib/session";

export type ActionState = { error: string | null };

/** A form field as text; files and missing fields are "". */
function raw(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function text(formData: FormData, name: string): string {
  return raw(formData, name).trim();
}

export async function login(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const email = text(formData, "email");
  // Not trimmed: spaces can be part of a password.
  const password = raw(formData, "password");
  if (!email || !password) {
    return { error: (await getTranslations("Errors"))("loginMissing") };
  }
  const response = await apiPostAnonymous("/auth/login", { email, password });
  if (!response.ok) {
    return { error: await errorMessage(response) };
  }
  const session = parseSessionCookie(response.headers.getSetCookie());
  if (session === null) {
    return { error: (await getTranslations("Errors"))("noSession") };
  }
  (await cookies()).set(SESSION_COOKIE, session.token, {
    httpOnly: true,
    secure: session.secure,
    sameSite: "lax",
    path: "/",
    maxAge: session.maxAge,
  });
  redirect("/invoices");
}

export async function logout(): Promise<void> {
  const cookieStore = await cookies();
  if (cookieStore.has(SESSION_COOKIE)) {
    await apiFetch("/auth/logout", { method: "POST" });
    cookieStore.delete(SESSION_COOKIE);
  }
  redirect("/login");
}

/** The language switch (ADR-027): keeps the choice in a cookie and renders the page again. */
export async function setLocale(formData: FormData): Promise<void> {
  const locale = formData.get("locale");
  if (!isLocale(locale)) {
    return;
  }
  (await cookies()).set(LOCALE_COOKIE, locale, {
    sameSite: "lax",
    path: "/",
    maxAge: LOCALE_COOKIE_MAX_AGE,
  });
  refresh();
}

type DecisionPath =
  | "approve"
  | "reject"
  | "override"
  | "override/confirm"
  | "override/decline"
  | "reopen";

async function decide(
  invoiceId: string,
  path: DecisionPath,
  body: Record<string, string | BookingChoice[]>,
): Promise<ActionState> {
  if (!isInvoiceId(invoiceId)) {
    return { error: (await getTranslations("Errors"))("unknownInvoice") };
  }
  const response = await apiFetch(`/invoices/${invoiceId}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 422) {
    return { error: (await getTranslations("Errors"))("reasonAndAccounts") };
  }
  if (!response.ok) {
    return { error: await errorMessage(response) };
  }
  refresh();
  return { error: null };
}

/** Approves a ready invoice with the account chosen per line (ADR-020). */
export async function approve(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  return decide(invoiceId, "approve", { bookings: bookingsFromForm(formData) });
}

export async function reject(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  return decide(invoiceId, "reject", { reason: text(formData, "reason") });
}

/** Four eyes (ADR-016), step 1: ask to approve a blocked invoice, with a reason. */
export async function requestOverride(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  if (formData.get("confirm") !== "on") {
    return { error: (await getTranslations("Errors"))("confirmChecked") };
  }
  return decide(invoiceId, "override", {
    reason: text(formData, "override_reason"),
  });
}

/** Four eyes, step 2 (approver, not the requester): confirm the override. */
export async function confirmOverride(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  return decide(invoiceId, "override/confirm", {
    reason: text(formData, "approver_reason"),
    bookings: bookingsFromForm(formData),
  });
}

/** Four eyes, step 2 (approver, not the requester): decline it; the invoice is blocked again. */
export async function declineOverride(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  return decide(invoiceId, "override/decline", {
    reason: text(formData, "approver_reason"),
  });
}

/** Reopens a rejected invoice with a reason (ADR-016): its checks run again, then it is in review. */
export async function reopen(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  return decide(invoiceId, "reopen", {
    reason: text(formData, "reopen_reason"),
  });
}

type ExportCreated = {
  id: string;
  invoice_count: number;
  without_tax_key: number;
  without_account_split: number;
  remaining: number;
};

/** Creates a DATEV export of the approved, not yet exported invoices (ADR-013). */
export async function exportDatev(): Promise<ExportState> {
  const response = await apiFetch("/exports/datev", { method: "POST" });
  if (!response.ok) {
    return { error: await errorMessage(response), export: null };
  }
  const created = (await response.json()) as ExportCreated;
  return {
    error: null,
    export: {
      id: created.id,
      invoiceCount: created.invoice_count,
      withoutTaxKey: created.without_tax_key,
      withoutAccountSplit: created.without_account_split,
      remaining: created.remaining,
    },
  };
}

/**
 * Asks the exception agent to investigate a blocked invoice (ADR-018): a live run with a model
 * key, else the recorded run for the case. The agent only proposes; it changes nothing.
 */
export async function investigate(invoiceId: string): Promise<ActionState> {
  if (!isInvoiceId(invoiceId)) {
    return { error: (await getTranslations("Errors"))("unknownInvoice") };
  }
  const response = await apiFetch(`/invoices/${invoiceId}/investigate`, {
    method: "POST",
  });
  if (!response.ok) {
    return { error: await errorMessage(response) };
  }
  refresh();
  return { error: null };
}

export type StatusState =
  | { status: InvoiceStatus; reason: string | null; error: null }
  | { status: null; reason: null; error: string };

/** The invoice's current status, for the upload page while processing runs (ADR-007). */
export async function invoiceStatus(invoiceId: string): Promise<StatusState> {
  if (!isInvoiceId(invoiceId)) {
    return {
      status: null,
      reason: null,
      error: (await getTranslations("Errors"))("unknownInvoice"),
    };
  }
  const response = await apiFetch(`/invoices/${invoiceId}`);
  if (!response.ok) {
    return {
      status: null,
      reason: null,
      error: await errorMessage(response),
    };
  }
  const invoice = (await response.json()) as Invoice;
  return { status: invoice.status, reason: invoice.status_reason, error: null };
}
