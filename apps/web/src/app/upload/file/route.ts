import { getTranslations } from "next-intl/server";

import { apiRequest } from "@/lib/api";
import { MAX_UPLOAD_BYTES, MAX_UPLOAD_MB } from "@/lib/upload";

// Room for the multipart boundaries and headers around the file.
const MULTIPART_OVERHEAD_BYTES = 64 * 1024;

function json(status: number, body: unknown): Response {
  return Response.json(body, { status });
}

/**
 * Passes an upload from the upload page on to `POST /invoices` with the user's session and
 * answers with the API's status and JSON. Not behind proxy.ts: the proxy buffers request bodies
 * with its own size limit, and this handler checks the session itself (401, no redirect).
 */
export async function POST(request: Request) {
  const t = await getTranslations("Upload.problems");
  const declared = Number(request.headers.get("Content-Length") ?? "0");
  if (declared > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES) {
    return json(413, { detail: t("tooLarge", { mb: MAX_UPLOAD_MB }) });
  }
  let file: FormDataEntryValue | null;
  try {
    file = (await request.formData()).get("file");
  } catch {
    return json(400, { detail: t("unreadable") });
  }
  if (!(file instanceof File)) {
    return json(422, { detail: t("chooseFile") });
  }
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await apiRequest("/invoices", {
    method: "POST",
    body: form,
  });
  if (response === null) {
    return json(401, { detail: t("session") });
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: the page shows a message for the status alone.
  }
  return json(response.status, body);
}
