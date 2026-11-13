"use server";

import { refresh } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiFetch, apiPostAnonymous, errorMessage } from "@/lib/api";
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

async function decide(
  invoiceId: string,
  action: "approve" | "reject",
  body: Record<string, string>,
): Promise<ActionState> {
  if (!isInvoiceId(invoiceId)) {
    return { error: "Unknown invoice." };
  }
  const response = await apiFetch(`/invoices/${invoiceId}/${action}`, {
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

export async function approve(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const overrideReason = text(formData, "override_reason");
  if (formData.has("override_reason")) {
    if (formData.get("confirm") !== "on") {
      return { error: "Confirm that you checked the failed checks." };
    }
    return decide(invoiceId, "approve", { override_reason: overrideReason });
  }
  return decide(invoiceId, "approve", {});
}

export async function reject(
  invoiceId: string,
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  return decide(invoiceId, "reject", { reason: text(formData, "reason") });
}
