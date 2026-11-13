import { cookies } from "next/headers";
import { redirect } from "next/navigation";

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

/** The API's error text: `detail` as a string, or a generic message for validation errors. */
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
  return `The API answered ${response.status}.`;
}

/**
 * Calls the API from the web server with the browser's session cookie (backend for frontend:
 * the browser never talks to the API directly). Without a valid session it redirects to /login.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    redirect("/login");
  }
  const headers = new Headers(init.headers);
  headers.set("Cookie", `${SESSION_COOKIE}=${token}`);
  const response = await fetch(`${baseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (response.status === 401) {
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
  return fetch(`${baseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
}
