"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";

import type { ActionState } from "@/app/actions";
import {
  type AgentRun,
  emailText,
  formatSeconds,
  formatUsd,
  type Investigation,
  runStatusLabel,
  stepLabel,
} from "@/lib/investigations";
import { formatDateTime } from "@/lib/invoices";

const INITIAL: ActionState = { error: null };
const BUTTON =
  "inline-flex h-9 w-fit items-center justify-center rounded-md border bg-background px-4 text-sm font-medium disabled:opacity-50";
// How often the page reloads the investigation while a live run is going on.
const POLL_MS = 2000;

function Steps({ run }: { run: AgentRun }) {
  if (run.steps.length === 0) {
    return null;
  }
  return (
    <details>
      <summary className="cursor-pointer text-xs text-muted-foreground">
        {run.steps.length} step(s): model calls and tool calls
      </summary>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 pr-2">#</th>
              <th className="py-1 pr-2">Step</th>
              <th className="py-1 pr-2">Tokens in/out</th>
              <th className="py-1 pr-2">Cost</th>
              <th className="py-1 pr-2">Time</th>
            </tr>
          </thead>
          <tbody>
            {run.steps.map((step) => (
              <tr key={step.id} className="border-t align-top">
                <td className="py-1 pr-2">{step.step_no}</td>
                <td className="py-1 pr-2">
                  <span className="font-mono break-all">{stepLabel(step)}</span>
                  {step.error && (
                    <p className="text-destructive">{step.error}</p>
                  )}
                  {step.kind === "tool" && step.result && (
                    <details>
                      <summary className="cursor-pointer text-muted-foreground">
                        Result
                      </summary>
                      <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">
                        {JSON.stringify(step.result, null, 2)}
                      </pre>
                    </details>
                  )}
                </td>
                <td className="py-1 pr-2 whitespace-nowrap">
                  {step.kind === "model"
                    ? `${step.input_tokens ?? "–"}/${step.output_tokens ?? "–"}`
                    : ""}
                </td>
                <td className="py-1 pr-2">
                  {step.cost_usd ? formatUsd(step.cost_usd) : ""}
                </td>
                <td className="py-1 pr-2 whitespace-nowrap">
                  {formatSeconds(step.latency_ms)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function EmailDraft({ run }: { run: AgentRun }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">
          Email draft to the supplier (German, not sent)
        </h3>
        <button
          type="button"
          className="text-xs underline underline-offset-4"
          onClick={() => {
            void navigator.clipboard.writeText(emailText(run)).then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="rounded-md border bg-muted p-3 text-sm whitespace-pre-wrap">
        {emailText(run)}
      </pre>
    </div>
  );
}

function RunSummary({ run }: { run: AgentRun }) {
  const recorded = run.source === "recorded";
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3 text-sm">
      <p className="text-xs text-muted-foreground">
        {runStatusLabel(run.status)}
        {recorded && run.recorded_at
          ? ` · recorded run from ${formatDateTime(run.recorded_at)} (no model on this server)`
          : ` · ${formatDateTime(run.started_at)}`}
        {` · ${run.model} · ${run.input_tokens}/${run.output_tokens} tokens · ${formatUsd(run.cost_usd)} · ${formatSeconds(run.duration_ms)}`}
      </p>
      {run.status === "running" && <p>The agent is investigating…</p>}
      {run.error && (
        <p role="status" className="text-amber-800">
          {run.error}
        </p>
      )}
      {run.finding && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium">Finding</h3>
          <p>{run.finding}</p>
        </div>
      )}
      {run.status === "completed" && <EmailDraft run={run} />}
      <Steps run={run} />
    </div>
  );
}

/**
 * The exception agent's investigation (ADR-018): it explains why the invoice is blocked and
 * drafts an email to the supplier. It only proposes; the decision stays with the reviewers.
 */
export function InvestigationPanel({
  investigation,
  investigate,
}: {
  investigation: Investigation;
  investigate: () => Promise<ActionState>;
}) {
  const router = useRouter();
  const [state, action, pending] = useActionState(investigate, INITIAL);
  const { run } = investigation;
  const running = run?.status === "running";

  useEffect(() => {
    if (!running) {
      return;
    }
    const timer = setInterval(() => router.refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [running, router]);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        The agent reads the ERP and the supplier registry (read only) and
        proposes an explanation and an email. It cannot approve or change the
        invoice.
      </p>
      {run && <RunSummary run={run} />}
      {investigation.can_investigate ? (
        <form action={action}>
          <button type="submit" className={BUTTON} disabled={pending}>
            {run ? "Investigate again" : "Investigate"}
          </button>
        </form>
      ) : (
        investigation.reason &&
        !running && (
          <p className="text-sm text-muted-foreground">
            {investigation.reason}
          </p>
        )
      )}
      {state.error && (
        <p role="alert" className="text-sm text-destructive">
          {state.error}
        </p>
      )}
    </div>
  );
}
