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

const STATUS_LABELS: Record<AgentRunStatus, string> = {
  running: "Running",
  completed: "Completed",
  stopped: "Stopped",
  failed: "Failed",
};

export function runStatusLabel(status: AgentRunStatus): string {
  return STATUS_LABELS[status];
}

/** "$0.004391" from the API's decimal string; whole cents are not enough for one call. */
export function formatUsd(value: string): string {
  return `$${Number(value).toFixed(6)}`;
}

/** "10.2 s" from milliseconds; "–" when unknown. */
export function formatSeconds(ms: number | null): string {
  return ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`;
}

/** What one step did, in a few words: "Model step" or "check_iban(DE58…)". */
export function stepLabel(step: AgentStep): string {
  if (step.kind === "model") {
    const action = step.result?.action;
    return typeof action === "string"
      ? `Model: ${action.replaceAll("_", " ")}`
      : "Model";
  }
  return `${step.tool}(${step.argument ?? ""})`;
}

/** The email draft as one text to copy: recipient, subject and body. */
export function emailText(run: AgentRun): string {
  return [
    run.email_to ? `To: ${run.email_to}` : null,
    `Subject: ${run.email_subject ?? ""}`,
    "",
    run.email_body ?? "",
  ]
    .filter((line) => line !== null)
    .join("\n");
}
