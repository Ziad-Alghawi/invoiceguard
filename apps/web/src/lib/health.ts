export type ApiHealth = "ok" | "unreachable";

const TIMEOUT_MS = 3000;

/**
 * Base URL of the InvoiceGuard API from the server-only `API_URL` variable.
 * Read on every call (not inlined at build), so one build works in every environment.
 */
export function getApiUrl(): string | undefined {
  return process.env.API_URL;
}

function isOkBody(body: unknown): boolean {
  return (
    typeof body === "object" &&
    body !== null &&
    "status" in body &&
    body.status === "ok"
  );
}

/**
 * Calls `GET {baseUrl}/health` on the InvoiceGuard API.
 * Any failure (missing URL, network error, timeout, non-2xx, unexpected body) is "unreachable".
 */
export async function checkApiHealth(
  baseUrl: string | undefined,
  fetchFn: typeof fetch = fetch,
): Promise<ApiHealth> {
  if (!baseUrl) {
    return "unreachable";
  }
  try {
    const response = await fetchFn(`${baseUrl.replace(/\/+$/, "")}/health`, {
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) {
      return "unreachable";
    }
    return isOkBody(await response.json()) ? "ok" : "unreachable";
  } catch {
    return "unreachable";
  }
}
