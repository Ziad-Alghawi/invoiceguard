import { apiFetch, notFoundResponse } from "@/lib/api";
import { isInvoiceId } from "@/lib/invoices";
import { viewQuery } from "@/lib/xrechnung";

/** Headers of the API's static view that the browser must see (ADR-029). */
const VIEW_HEADERS = [
  "Content-Type",
  "Content-Security-Policy",
  "X-Content-Type-Options",
  "Cache-Control",
];

/**
 * The readable XRechnung view (KoSIT visualization) from the API with the user's session. It is
 * shown in a sandboxed iframe; the API's CSP keeps it static even when opened on its own.
 */
export async function GET(
  request: Request,
  { params }: RouteContext<"/invoices/[id]/view">,
) {
  const { id } = await params;
  const query = viewQuery(new URL(request.url).searchParams);
  if (!isInvoiceId(id) || query === null) {
    return notFoundResponse();
  }
  const upstream = await apiFetch(`/invoices/${id}/view?${query}`);
  if (!upstream.ok) {
    return notFoundResponse(upstream.status);
  }
  const headers = new Headers();
  for (const name of VIEW_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) {
      headers.set(name, value);
    }
  }
  return new Response(upstream.body, { headers });
}
