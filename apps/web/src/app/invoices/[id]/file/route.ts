import { apiDownload } from "@/lib/api";
import { isInvoiceId } from "@/lib/invoices";

/** Streams the original upload from the API with the user's session, as a download. */
export async function GET(
  _request: Request,
  { params }: RouteContext<"/invoices/[id]/file">,
) {
  const { id } = await params;
  if (!isInvoiceId(id)) {
    return new Response("Not found", { status: 404 });
  }
  return apiDownload(`/invoices/${id}/file`);
}
