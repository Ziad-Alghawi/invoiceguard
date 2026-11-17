"use server";

import { refresh } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiFetch, apiPostAnonymous, errorMessage } from "@/lib/api";
import type { ExportState } from "@/lib/exports";
import { isInvoiceId } from "@/lib/invoices";
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
    return { error: "Enter your email and password." };
  }
  const response = await apiPostAnonymous("/auth/login", { email, password });
  if (!response.ok) {
    return { error: await errorMessage(response) };
  }
  const session = parseSessionCookie(response.headers.getSetCookie());
  if (session === null) {
    return { error: "The API did not start a session." };
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

type DecisionPath =
  "approve" | "reject" | "override" | "override/confirm" | "override/decline";

async function decide(
  invoiceId: string,
  path: DecisionPath,
  body: Record<string, string>,
): Promise<ActionState> {
  if (!isInvoiceId(invoiceId)) {
    return { error: "Unknown invoice." };
  }
  const response = await apiFetch(`/invoices/${invoiceId}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 422) {
    return { error: "Enter a reason; it cannot be empty." };
  }
  if (!response.ok) {
    return { error: await errorMessage(response) };
  }
  refresh();
  return { error: null };
}

export async function approve(invoiceId: string): Promise<ActionState> {
  return decide(invoiceId, "approve", {});
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
    return { error: "Confirm that you checked the failed checks." };
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

type ExportCreated = {
  id: string;
  invoice_count: number;
  without_tax_key: number;
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
      remaining: created.remaining,
    },
  };
}
