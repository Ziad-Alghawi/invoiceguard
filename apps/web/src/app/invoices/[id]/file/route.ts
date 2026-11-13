import { apiFetch } from "@/lib/api";
import { isInvoiceId } from "@/lib/invoices";

const PASSED_HEADERS = [
  "Content-Type",
  "Content-Disposition",
  "Content-Length",
];

/** Streams the original upload from the API with the user's session, as a download. */
export async function GET(
  _request: Request,
  { params }: RouteContext<"/invoices/[id]/file">,
) {
  const { id } = await params;
  if (!isInvoiceId(id)) {
    return new Response("Not found", { status: 404 });
  }
  const upstream = await apiFetch(`/invoices/${id}/file`);
  if (!upstream.ok) {
    return new Response("Not found", { status: upstream.status });
  }
  const headers = new Headers({ "X-Content-Type-Options": "nosniff" });
  for (const name of PASSED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) {
      headers.set(name, value);
    }
  }
  return new Response(upstream.body, { headers });
}
