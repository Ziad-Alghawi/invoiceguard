/**
 * Invoice upload from the browser (R2-7). The checks here only give a quick message before the
 * file is sent; the API decides (type from the content, size, duplicates, demo rules).
 */

import type { InvoiceStatus } from "@/lib/invoices";

/** The API's default limit (INVOICEGUARD_MAX_UPLOAD_BYTES); the API answers 413 above its own. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = [".xml", ".pdf"] as const;
/** The route handler that passes the upload on to the API with the session. */
export const UPLOAD_PATH = "/upload/file";

/** The API's answer to `POST /invoices`, as the route handler passes it on. */
export type UploadResponse = { status: number; body: unknown };

export type UploadOutcome =
  | { kind: "accepted"; invoiceId: string }
  | { kind: "error"; message: string; existingId: string | null };

/** Why the file cannot be uploaded, or null when it may be sent. */
export function checkFile(file: { name: string; size: number }): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return "Choose an XRechnung XML file or a ZUGFeRD / Factur-X PDF (.xml or .pdf).";
  }
  if (file.size === 0) {
    return "The file is empty.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `The file is larger than ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB.`;
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
  const error = (text: string, existingId: string | null = null) => ({
    kind: "error" as const,
    message: text,
    existingId,
  });

  if (status === 202) {
    const id = field(body, "id");
    return typeof id === "string"
      ? { kind: "accepted", invoiceId: id }
      : error("The API did not return the new invoice.");
  }
  if (status === 409) {
    const existing = field(detail, "invoice_id");
    return error(
      "This file was already uploaded.",
      typeof existing === "string" ? existing : null,
    );
  }
  if (status === 401) {
    return error("Your session has ended. Log in again.");
  }
  if (status === 413) {
    return error(message ?? "The file is too large.");
  }
  if (status === 415) {
    return error(
      message ??
        "Upload an XML or PDF invoice; the file extension must match its content.",
    );
  }
  if (status === 422 && message !== null) {
    return error(message);
  }
  if (status === 429) {
    return error(message ?? "Too many uploads. Try again later.");
  }
  return error(message ?? `The upload failed (${status}).`);
}

/** Statuses processing passes through; the page polls until the invoice has left them. */
export function isProcessing(status: InvoiceStatus): boolean {
  return status === "received" || status === "processing";
}

/** One line on what the new invoice's status means for the user. */
export function statusSummary(status: InvoiceStatus): string {
  switch (status) {
    case "ready":
      return "All checks passed. The invoice is ready for review.";
    case "blocked":
      return "At least one check failed. The invoice is blocked and waits for review.";
    case "awaiting_extraction":
      return "The PDF has no embedded XML and waits for LLM extraction.";
    case "failed":
      return "The invoice could not be read. It is in the queue with the reason.";
    default:
      return `The invoice is ${status.replaceAll("_", " ")}.`;
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
    request.onerror = () => reject(new Error("The upload was interrupted."));
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });
}
