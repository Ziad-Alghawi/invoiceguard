/**
 * Invoice upload from the browser (R2-7). The checks here only give a quick message before the
 * file is sent; the API decides (type from the content, size, duplicates, demo rules).
 */

import type { InvoiceStatus } from "@/lib/invoices";

/** The API's default limit (INVOICEGUARD_MAX_UPLOAD_BYTES); the API answers 413 above its own. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const MAX_UPLOAD_MB = MAX_UPLOAD_BYTES / (1024 * 1024);
export const ACCEPTED_EXTENSIONS = [".xml", ".pdf"] as const;
/** The route handler that passes the upload on to the API with the session. */
export const UPLOAD_PATH = "/upload/file";

/** The API's answer to `POST /invoices`, as the route handler passes it on. */
export type UploadResponse = { status: number; body: unknown };

/** A message key in "Upload.problems" and its values. */
export type UploadProblem =
  | {
      key:
        | "chooseFile"
        | "wrongType"
        | "empty"
        | "interrupted"
        | "noInvoice"
        | "duplicate"
        | "session"
        | "tooLargeApi"
        | "unsupported"
        | "tooMany";
    }
  | { key: "tooLarge"; values: { mb: number } }
  | { key: "failed"; values: { status: number } };

export type UploadOutcome =
  | { kind: "accepted"; invoiceId: string }
  | {
      kind: "error";
      /** The API's own message (English, ADR-027), shown instead of the problem when present. */
      detail: string | null;
      problem: UploadProblem;
      existingId: string | null;
    };

/** Why the file cannot be uploaded, or null when it may be sent. */
export function checkFile(file: {
  name: string;
  size: number;
}): UploadProblem | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return { key: "wrongType" };
  }
  if (file.size === 0) {
    return { key: "empty" };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return { key: "tooLarge", values: { mb: MAX_UPLOAD_MB } };
  }
  return null;
}

function field(body: unknown, name: string): unknown {
  return typeof body === "object" && body !== null && name in body
    ? (body as Record<string, unknown>)[name]
    : undefined;
}

/** Turns the API's answer into the new invoice or a message for the user. */
export function uploadOutcome({ status, body }: UploadResponse): UploadOutcome {
  const detail = field(body, "detail");
  const message = typeof detail === "string" ? detail : null;
  const error = (
    problem: UploadProblem,
    apiDetail: string | null = null,
    existingId: string | null = null,
  ): UploadOutcome => ({
    kind: "error",
    detail: apiDetail,
    problem,
    existingId,
  });

  if (status === 202) {
    const id = field(body, "id");
    return typeof id === "string"
      ? { kind: "accepted", invoiceId: id }
      : error({ key: "noInvoice" });
  }
  if (status === 409) {
    const existing = field(detail, "invoice_id");
    return error(
      { key: "duplicate" },
      null,
      typeof existing === "string" ? existing : null,
    );
  }
  if (status === 401) {
    return error({ key: "session" });
  }
  if (status === 413) {
    return error({ key: "tooLargeApi" }, message);
  }
  if (status === 415) {
    return error({ key: "unsupported" }, message);
  }
  if (status === 429) {
    return error({ key: "tooMany" }, message);
  }
  return error({ key: "failed", values: { status } }, message);
}

/** Statuses processing passes through; the page polls until the invoice has left them. */
export function isProcessing(status: InvoiceStatus): boolean {
  return status === "received" || status === "processing";
}

/** The message key in "Upload.summary" on what the new invoice's status means. */
export type StatusSummary =
  "ready" | "blocked" | "awaitingExtraction" | "failed" | "other";

export function statusSummary(status: InvoiceStatus): StatusSummary {
  switch (status) {
    case "ready":
      return "ready";
    case "blocked":
      return "blocked";
    case "awaiting_extraction":
      return "awaitingExtraction";
    case "failed":
      return "failed";
    default:
      return "other";
  }
}

/** Sends the file with XMLHttpRequest, which reports upload progress (fetch does not). */
export function sendFile(
  file: File,
  onProgress: (percent: number) => void,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", UPLOAD_PATH);
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onload = () =>
      resolve({ status: request.status, body: request.response as unknown });
    request.onerror = () => reject(new Error("upload interrupted"));
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });
}
