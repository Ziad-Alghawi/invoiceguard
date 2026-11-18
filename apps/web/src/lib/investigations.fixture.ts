/** A completed investigation as the API returns it, for the web tests. */
import type { AgentRun, AgentStep } from "@/lib/investigations";

export const STEP: AgentStep = {
  id: 1,
  step_no: 1,
  kind: "model",
  tool: null,
  argument: null,
  result: { action: "call_tools" },
  input_tokens: 1342,
  output_tokens: 139,
  cost_usd: "0.001528",
  latency_ms: 2621,
  error: null,
  at: "2026-11-18T00:29:38Z",
};

export const RUN: AgentRun = {
  id: "8596e4d4-674d-43df-9c74-7ee3c3100dd8",
  status: "completed",
  source: "live",
  stop_reason: null,
  error: null,
  model: "gemini/gemini-3.8-flash",
  finding: "The IBAN is not registered to any supplier.",
  email_to: "buchhaltung@demo-it-service.example",
  email_subject: "Rückfrage zu Rechnung 2026-IT-0816",
  email_body: "Guten Tag,\n\n...\n\nMit freundlichen Grüßen",
  input_tokens: 5216,
  output_tokens: 559,
  cost_usd: "0.006008",
  started_at: "2026-11-18T00:30:00Z",
  finished_at: "2026-11-18T00:30:12Z",
  duration_ms: 12091,
  recorded_at: null,
  steps: [
    STEP,
    {
      ...STEP,
      id: 2,
      kind: "tool",
      tool: "check_iban",
      argument: "DE58876543210000000099", // pragma: allowlist secret
      result: { registered_to: [] },
      input_tokens: null,
      output_tokens: null,
      cost_usd: null,
      latency_ms: 59,
    },
  ],
};
