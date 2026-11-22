"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type { StatusState } from "@/app/actions";
import { StatusReason } from "@/components/status-reason";
import type { InvoiceStatus, Reason } from "@/lib/invoices";
import {
  ACCEPTED_EXTENSIONS,
  checkFile,
  isProcessing,
  sendFile,
  statusSummary,
  type UploadProblem,
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
      reason: Reason | null;
    }
  | {
      name: "error";
      detail: string | null;
      problem: UploadProblem;
      existingId: string | null;
    };

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
  const t = useTranslations("Upload");
  const codes = useTranslations("Codes.invoiceStatus");
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

  function problemText(problem: UploadProblem): string {
    return "values" in problem
      ? t(`problems.${problem.key}`, problem.values)
      : t(`problems.${problem.key}`);
  }

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
        detail: null,
        problem: { key: "chooseFile" },
        existingId: null,
      });
      return;
    }
    const problem = checkFile(file);
    if (problem !== null) {
      setPhase({ name: "error", detail: null, problem, existingId: null });
      return;
    }
    setPhase({ name: "uploading", percent: 0 });
    let response: UploadResponse;
    try {
      response = await send(file, (percent) =>
        setPhase({ name: "uploading", percent }),
      );
    } catch {
      setPhase({
        name: "error",
        detail: null,
        problem: { key: "interrupted" },
        existingId: null,
      });
      return;
    }
    const outcome = uploadOutcome(response);
    if (outcome.kind === "error") {
      setPhase({
        name: "error",
        detail: outcome.detail,
        problem: outcome.problem,
        existingId: outcome.existingId,
      });
      return;
    }
    await waitForProcessing(outcome.invoiceId);
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          {t("file")}
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
          {busy ? t("uploading") : t("upload")}
        </button>
      </form>

      {phase.name === "uploading" && (
        <label className="flex flex-col gap-1 text-sm">
          {t("progress", { percent: phase.percent })}
          <progress max={100} value={phase.percent} className="w-full" />
        </label>
      )}
      {phase.name === "processing" && (
        <p role="status" className="text-sm">
          {t("checking")}
        </p>
      )}
      {phase.name === "done" && (
        <div role="status" className="flex flex-col gap-1 text-sm">
          <p>
            {phase.status === null
              ? t("uploaded")
              : isProcessing(phase.status)
                ? t("slow")
                : t(`summary.${statusSummary(phase.status)}`, {
                    status: codes(phase.status),
                  })}
          </p>
          {phase.reason && (
            <p className="text-muted-foreground">
              <StatusReason reason={phase.reason} />
            </p>
          )}
          <Link
            href={`/invoices/${phase.invoiceId}`}
            className="underline underline-offset-4"
          >
            {t("open")}
          </Link>
        </div>
      )}
      {phase.name === "error" && (
        <div
          role="alert"
          className="flex flex-col gap-1 text-sm text-destructive"
        >
          <p>{phase.detail ?? problemText(phase.problem)}</p>
          {phase.existingId && (
            <Link
              href={`/invoices/${phase.existingId}`}
              className="underline underline-offset-4"
            >
              {t("openExisting")}
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
