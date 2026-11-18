"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type { StatusState } from "@/app/actions";
import type { InvoiceStatus } from "@/lib/invoices";
import {
  ACCEPTED_EXTENSIONS,
  checkFile,
  isProcessing,
  sendFile,
  statusSummary,
  type UploadResponse,
  uploadOutcome,
} from "@/lib/upload";

const POLL_INTERVAL_MS = 1000;
// XML is processed in well under a second; a PDF with LLM extraction takes about 10 s.
const POLL_TIMEOUT_MS = 60_000;

type Phase =
  | { name: "idle" }
  | { name: "uploading"; percent: number }
  | { name: "processing"; invoiceId: string }
  | {
      name: "done";
      invoiceId: string;
      status: InvoiceStatus | null;
      reason: string | null;
    }
  | { name: "error"; message: string; existingId: string | null };

const BUTTON =
  "inline-flex h-9 w-fit items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50";

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Uploads one invoice file, shows the upload progress, then waits for processing and links to
 * the new invoice. `send` and `getStatus` are the network calls, replaceable in tests.
 */
export function UploadForm({
  getStatus,
  send = sendFile,
  pollIntervalMs = POLL_INTERVAL_MS,
}: {
  getStatus: (invoiceId: string) => Promise<StatusState>;
  send?: (
    file: File,
    onProgress: (percent: number) => void,
  ) => Promise<UploadResponse>;
  pollIntervalMs?: number;
}) {
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const mounted = useRef(true);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const busy = phase.name === "uploading" || phase.name === "processing";

  async function waitForProcessing(invoiceId: string) {
    setPhase({ name: "processing", invoiceId });
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    while (mounted.current) {
      const state = await getStatus(invoiceId);
      if (state.error !== null) {
        setPhase({ name: "done", invoiceId, status: null, reason: null });
        return;
      }
      if (!isProcessing(state.status) || Date.now() >= deadline) {
        setPhase({
          name: "done",
          invoiceId,
          status: state.status,
          reason: state.reason,
        });
        return;
      }
      await wait(pollIntervalMs);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = input.current?.files?.[0];
    if (file === undefined) {
      setPhase({
        name: "error",
        message: "Choose a file to upload.",
        existingId: null,
      });
      return;
    }
    const problem = checkFile(file);
    if (problem !== null) {
      setPhase({ name: "error", message: problem, existingId: null });
      return;
    }
    setPhase({ name: "uploading", percent: 0 });
    let response: UploadResponse;
    try {
      response = await send(file, (percent) =>
        setPhase({ name: "uploading", percent }),
      );
    } catch (error) {
      setPhase({
        name: "error",
        message: error instanceof Error ? error.message : "The upload failed.",
        existingId: null,
      });
      return;
    }
    const outcome = uploadOutcome(response);
    if (outcome.kind === "error") {
      setPhase({ name: "error", ...outcome });
      return;
    }
    await waitForProcessing(outcome.invoiceId);
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Invoice file
          <input
            ref={input}
            type="file"
            name="file"
            accept={ACCEPTED_EXTENSIONS.join(",")}
            disabled={busy}
            className="rounded-md border bg-background p-2 text-sm"
          />
        </label>
        <button type="submit" disabled={busy} className={BUTTON}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </form>

      {phase.name === "uploading" && (
        <label className="flex flex-col gap-1 text-sm">
          Uploading {phase.percent} %
          <progress max={100} value={phase.percent} className="w-full" />
        </label>
      )}
      {phase.name === "processing" && (
        <p role="status" className="text-sm">
          Uploaded. Checking the invoice…
        </p>
      )}
      {phase.name === "done" && (
        <div role="status" className="flex flex-col gap-1 text-sm">
          <p>
            {phase.status === null
              ? "Uploaded."
              : isProcessing(phase.status)
                ? "Uploaded. Processing takes longer than usual; the invoice page shows the result."
                : statusSummary(phase.status)}
          </p>
          {phase.reason && (
            <p className="text-muted-foreground">{phase.reason}</p>
          )}
          <Link
            href={`/invoices/${phase.invoiceId}`}
            className="underline underline-offset-4"
          >
            Open the invoice
          </Link>
        </div>
      )}
      {phase.name === "error" && (
        <div
          role="alert"
          className="flex flex-col gap-1 text-sm text-destructive"
        >
          <p>{phase.message}</p>
          {phase.existingId && (
            <Link
              href={`/invoices/${phase.existingId}`}
              className="underline underline-offset-4"
            >
              Open the existing invoice
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
