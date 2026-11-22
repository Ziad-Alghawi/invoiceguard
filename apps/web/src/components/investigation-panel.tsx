"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useActionState, useEffect, useState } from "react";

import type { ActionState } from "@/app/actions";
import {
  type AgentRun,
  type AgentStep,
  emailText,
  formatSeconds,
  formatUsd,
  type Investigation,
  modelAction,
  toolCall,
} from "@/lib/investigations";
import { formatDateTime } from "@/lib/invoices";

const INITIAL: ActionState = { error: null };
const BUTTON =
  "inline-flex h-9 w-fit items-center justify-center rounded-md border bg-background px-4 text-sm font-medium disabled:opacity-50";
// How often the page reloads the investigation while a live run is going on.
const POLL_MS = 2000;

function StepLabel({ step }: { step: AgentStep }) {
  const t = useTranslations("Investigation");
  if (step.kind === "tool") {
    return toolCall(step);
  }
  const action = modelAction(step);
  return action === null ? t("model") : t("modelAction", { action });
}

function Steps({ run }: { run: AgentRun }) {
  const t = useTranslations("Investigation");
  const locale = useLocale();
  if (run.steps.length === 0) {
    return null;
  }
  return (
    <details>
      <summary className="cursor-pointer text-xs text-muted-foreground">
        {t("steps", { count: run.steps.length })}
      </summary>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 pr-2">{t("stepNo")}</th>
              <th className="py-1 pr-2">{t("step")}</th>
              <th className="py-1 pr-2">{t("tokens")}</th>
              <th className="py-1 pr-2">{t("cost")}</th>
              <th className="py-1 pr-2">{t("time")}</th>
            </tr>
          </thead>
          <tbody>
            {run.steps.map((step) => (
              <tr key={step.id} className="border-t align-top">
                <td className="py-1 pr-2">{step.step_no}</td>
                <td className="py-1 pr-2">
                  <span className="font-mono break-all">
                    <StepLabel step={step} />
                  </span>
                  {step.error && (
                    <p className="text-destructive">{step.error}</p>
                  )}
                  {step.kind === "tool" && step.result && (
                    <details>
                      <summary className="cursor-pointer text-muted-foreground">
                        {t("result")}
                      </summary>
                      <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">
                        {JSON.stringify(step.result, null, 2)}
                      </pre>
                    </details>
                  )}
                </td>
                <td className="py-1 pr-2 whitespace-nowrap">
                  {step.kind === "model" &&
                    t("stepTokens", {
                      input: step.input_tokens ?? t("unknown"),
                      output: step.output_tokens ?? t("unknown"),
                    })}
                </td>
                <td className="py-1 pr-2">
                  {step.cost_usd && formatUsd(step.cost_usd, locale)}
                </td>
                <td className="py-1 pr-2 whitespace-nowrap">
                  {formatSeconds(step.latency_ms, locale)}
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
  const t = useTranslations("Investigation");
  const [copied, setCopied] = useState(false);
  const text = emailText(run, {
    to: (to) => t("emailTo", { to }),
    subject: (subject) => t("emailSubject", { subject }),
  });
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{t("emailTitle")}</h3>
        <button
          type="button"
          className="text-xs underline underline-offset-4"
          onClick={() => {
            void navigator.clipboard.writeText(text).then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? t("copied") : t("copy")}
        </button>
      </div>
      <pre
        lang="de"
        className="rounded-md border bg-muted p-3 text-sm whitespace-pre-wrap"
      >
        {text}
      </pre>
    </div>
  );
}

function RunSummary({ run }: { run: AgentRun }) {
  const t = useTranslations("Investigation");
  const codes = useTranslations("Codes.runStatus");
  const locale = useLocale();
  const recordedAt = run.source === "recorded" ? run.recorded_at : null;
  const values = {
    status: codes(run.status),
    date: formatDateTime(recordedAt ?? run.started_at, locale),
    model: run.model,
    input: run.input_tokens,
    output: run.output_tokens,
    cost: formatUsd(run.cost_usd, locale),
    duration: formatSeconds(run.duration_ms, locale),
  };
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3 text-sm">
      <p className="text-xs text-muted-foreground">
        {t(recordedAt ? "metaRecorded" : "metaLive", values)}
      </p>
      {run.status === "running" && <p>{t("running")}</p>}
      {run.error && (
        <p role="status" className="text-amber-800">
          {run.error}
        </p>
      )}
      {run.finding && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium">{t("finding")}</h3>
          <p lang="en">{run.finding}</p>
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
  const t = useTranslations("Investigation");
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
      <p className="text-sm text-muted-foreground">{t("intro")}</p>
      {run && <RunSummary run={run} />}
      {investigation.can_investigate ? (
        <form action={action}>
          <button type="submit" className={BUTTON} disabled={pending}>
            {run ? t("investigateAgain") : t("investigate")}
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
