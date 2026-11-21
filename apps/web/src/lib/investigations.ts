/** The exception agent's investigation of an invoice (ADR-018), as `GET /invoices/{id}/investigation` returns it. */

export type AgentRunStatus = "running" | "completed" | "stopped" | "failed";

export type AgentStep = {
  id: number;
  step_no: number;
  kind: "model" | "tool";
  tool: string | null;
  argument: string | null;
  result: Record<string, unknown> | null;
  input_tokens: number | null;
  output_tokens: number | null;
  /** Decimal string in US dollars; null for tool calls. */
  cost_usd: string | null;
  latency_ms: number;
  error: string | null;
  at: string;
};

export type AgentRun = {
  id: string;
  status: AgentRunStatus;
  source: "live" | "recorded";
  stop_reason: string | null;
  error: string | null;
  model: string;
  finding: string | null;
  email_to: string | null;
  email_subject: string | null;
  email_body: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  recorded_at: string | null;
  steps: AgentStep[];
};

export type Investigation = {
  run: AgentRun | null;
  mode: "live" | "recorded" | "unavailable";
  can_investigate: boolean;
  reason: string | null;
};

/** "$0.004391" (en) or "0,004391 $" (de) from the API's decimal string; cents are too coarse. */
export function formatUsd(value: string, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 6,
    maximumFractionDigits: 6,
  }).format(Number(value));
}

/** "10.2 s" (en) or "10,2 s" (de) from milliseconds; "–" when unknown. */
export function formatSeconds(ms: number | null, locale: string): string {
  if (ms === null) {
    return "–";
  }
  const seconds = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(ms / 1000);
  return `${seconds} s`;
}

/** The action a model step chose, in words ("call tools"); null when it chose none. */
export function modelAction(step: AgentStep): string | null {
  const action = step.result?.action;
  return typeof action === "string" ? action.replaceAll("_", " ") : null;
}

/** A tool step as the call it made: "check_iban(DE58…)". */
export function toolCall(step: AgentStep): string {
  return `${step.tool}(${step.argument ?? ""})`;
}

/** The "To:" and "Subject:" lines in the UI language. */
export type EmailLabels = {
  to: (address: string) => string;
  subject: (subject: string) => string;
};

/** The email draft as one text to copy: recipient, subject and body. */
export function emailText(run: AgentRun, labels: EmailLabels): string {
  return [
    run.email_to ? labels.to(run.email_to) : null,
    labels.subject(run.email_subject ?? ""),
    "",
    run.email_body ?? "",
  ]
    .filter((line) => line !== null)
    .join("\n");
}
