import { cookies, headers as nextHeaders } from "next/headers";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { getApiUrl } from "@/lib/health";
import { SESSION_COOKIE } from "@/lib/session";

const TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function baseUrl(): string {
  const url = getApiUrl();
  if (!url) {
    throw new Error("API_URL is not set");
  }
  return url.replace(/\/+$/, "");
}

/**
 * The API's error text: `detail` as a string (English, ADR-027), or a generic message in the UI
 * language for validation errors and answers without one.
 */
export async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    // Not JSON: fall through to the generic message.
  }
  return (await getTranslations("Errors"))("apiStatus", {
    status: response.status,
  });
}

/**
 * Calls the API with the browser's session cookie and returns its answer as it is, 401
 * included; null without a session cookie. For route handlers that answer a script, which
 * cannot follow a redirect to /login.
 */
export async function apiRequest(
  path: string,
  init: RequestInit = {},
): Promise<Response | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return null;
  }
  const headers = new Headers(init.headers);
  headers.set("Cookie", `${SESSION_COOKIE}=${token}`);
  return fetch(`${baseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
}

/**
 * Calls the API from the web server with the browser's session cookie (backend for frontend:
 * the browser never talks to the API directly). Without a valid session it redirects to /login.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const response = await apiRequest(path, init);
  if (response === null || response.status === 401) {
    redirect("/login");
  }
  return response;
}

/** GET a JSON resource; non-2xx answers throw an ApiError. */
export async function apiGet<T>(path: string): Promise<T> {
  const response = await apiFetch(path);
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return (await response.json()) as T;
}

/** POST without a session, for login. */
export async function apiPostAnonymous(
  path: string,
  body: unknown,
): Promise<Response> {
  const headers = new Headers({ "Content-Type": "application/json" });
  // The browser's address as the edge proxy (Caddy) reported it, for the API's per-IP login
  // limit. The API believes it only from trusted proxies (INVOICEGUARD_TRUSTED_PROXIES).
  const forwardedFor = (await nextHeaders()).get("x-forwarded-for");
  if (forwardedFor) {
    headers.set("X-Forwarded-For", forwardedFor);
  }
  return fetch(`${baseUrl()}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
}

const DOWNLOAD_HEADERS = [
  "Content-Type",
  "Content-Disposition",
  "Content-Length",
];

/** A plain-text error for a download that cannot be served, in the UI language. */
export async function notFoundResponse(status = 404): Promise<Response> {
  const t = await getTranslations("Errors");
  return new Response(t("notFound"), { status });
}

/** Streams a file download from the API with the user's session (route handlers). */
export async function apiDownload(path: string): Promise<Response> {
  const upstream = await apiFetch(path);
  if (!upstream.ok) {
    return notFoundResponse(upstream.status);
  }
  const headers = new Headers({ "X-Content-Type-Options": "nosniff" });
  for (const name of DOWNLOAD_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) {
      headers.set(name, value);
    }
  }
  return new Response(upstream.body, { headers });
}
