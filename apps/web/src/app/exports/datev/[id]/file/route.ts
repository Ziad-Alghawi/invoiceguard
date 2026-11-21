import { apiDownload, notFoundResponse } from "@/lib/api";
import { isInvoiceId } from "@/lib/invoices";

/** Streams a DATEV export file from the API with the user's session, as a download. */
export async function GET(
  _request: Request,
  { params }: RouteContext<"/exports/datev/[id]/file">,
) {
  const { id } = await params;
  // Export IDs are UUIDs, like invoice IDs.
  if (!isInvoiceId(id)) {
    return notFoundResponse();
  }
  return apiDownload(`/exports/datev/${id}/file`);
}
