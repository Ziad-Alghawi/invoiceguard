# ADR-018: Exception agent: an own bounded loop outside the graph, with a per-invoice cost cap

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

A blocked invoice tells the reviewer *that* a check failed (an IBAN not in the registry, a price above the order).
What to do next takes digging: is the IBAN registered to another supplier, was the order delivered, what did we
order at which price, and what to write to the supplier. That is reasoning over a few lookups, which ADR-002 allows
an LLM to do, as long as it only proposes.

Constraints:

- **The agent proposes, humans decide** (PLAN §3, ADR-003). It must not be able to change an invoice's status,
  approve, or resume the approval graph, whatever the model returns.
- **Invoice text is untrusted** and may be written to steer a model (R2-4 found such invoices). Tool results are
  data too.
- **Spending is capped** (PLAN §3: about €20 for six weeks; the demo has a daily budget, ADR-014).
- The tools are the read-only MCP servers of ADR-017.
- `LLMClient` (ADR-004) has one method, `structured()`: one JSON answer that follows a schema. It has no
  provider-native tool calling.
- The public demo has no model key (ADR-010, data protection), but should still show what the agent does.

## Decision

**An own loop, no agent framework.** `invoiceguard_api/agent/` runs a loop of at most `max_steps` model calls over
`LLMClient.structured()`. Each reply is one JSON action that follows a strict schema:

- `{"action": "call_tools", "tool_calls": [{"tool": ..., "argument": ...}]}` (1 to 3 calls), or
- `{"action": "finish", "finding": ..., "email_subject": ..., "email_body": ...}`.

`tool` is an enum of the seven read-only MCP tools (ADR-017); each takes exactly one argument (a VAT ID, an IBAN or
an order number), so a call is a name and a string. The allow-list is enforced twice: by the schema, and again in
code before anything is sent to an MCP server. There is no action to approve, change a status or send an email, and
the agent module has no access to the graph, the status column or the decision endpoints. The German email draft is
an output of the loop, not a tool: nothing is sent.

**Limits, all from settings (`INVOICEGUARD_AGENT_*`), checked before every model call and every tool call:**

| Limit | Default | When reached |
| --- | --- | --- |
| `max_steps` (model calls) | 8 | `stopped`, reason `max_steps` |
| `max_tool_calls` | 12 | `stopped`, reason `max_tool_calls` |
| `cost_cap_usd` per invoice | 0.05 | `stopped`, reason `cost_cap` |
| `timeout_seconds` per run | 90 | `stopped`, reason `timeout` |

The cost cap counts every agent call ever made for the invoice (`model_calls` with purpose `agent`), so investigating
again cannot exceed it. It is checked before a call, so the last call can overshoot by its own cost. The daily LLM
budget (ADR-014) is checked before a run starts. A stopped run keeps its steps but has no finding or email. An
invalid reply gets one correction (the validation errors, never the reply's values, go back to the model); a second
one fails the run, as does an LLM error or an unknown price (ADR-004). The prompt tells the model how many steps and
tool calls are left, so it finishes in time.

**Untrusted data stays data.** The system prompt is a constant. The user message holds the invoice's fields and its
failed and warning checks as JSON between `<<<UNTRUSTED_INVOICE>>>` markers, and every tool result as JSON between
`<<<UNTRUSTED_TOOL_RESULT>>>` markers; raw XML or PDF content is never sent. An invoice whose `prompt_injection`
check failed (R2-4) is **not sent to the model at all**: the endpoint refuses, the automatic run skips it, and the UI
says why. The email's recipient comes from `suppliers.contact_email` in the master data, set by code, never from an
address printed on the invoice or chosen by the model.

**Outside the graph.** The agent is not a node of the LangGraph processing graph (ADR-015), contrary to PLAN §5's
first sketch. It runs as a background task after processing leaves an invoice `blocked`, or when a user clicks
"Investigate" (`POST /invoices/{id}/investigate`). It never takes the invoice's advisory lock, so a reviewer is not
held up while it runs (seconds to a minute), and it holds no reference to the graph, so it cannot resume a thread by
construction rather than by convention. The approval gate is unchanged. A partial unique index allows one running
investigation per invoice; a run left `running` by a restart is marked `failed` at startup.

**Every step is saved and shown.** `agent_runs` (status, stop reason, model, finding, email, totals) and
`agent_steps` (per model call: tokens, cost, latency; per tool call: tool, argument, result, latency, error). Model
calls also go to `model_calls` (purpose `agent`), so the cost per invoice and the daily budget include them. The
invoice page shows the finding, the email draft, every step and the totals.

**Language.** The finding is English (the UI language today; German UI in R5), the email draft German (PLAN §3).

**Demo without a key.** With no model key (or no MCP URLs) the "Investigate" button loads a **recorded run**: the
result of a real local run, stored in `agent/recorded/`, matched by scenario (the seller's VAT ID and the set of
failed checks, so a re-upload with another invoice number matches too). It is saved with `source = recorded` and
labelled in the UI with the original date, model and cost; it is never presented as live. A case without a
recording gets a clear `409`.

## Alternatives

- **LangGraph's prebuilt ReAct agent or LangChain tools:** less code, but it needs provider tool calling through
  LangChain's model classes instead of our `LLMClient` (cost logging, price checks, ADR-004), and its limits
  (recursion limit) do not cover cost or tool-call counts.
- **Add native tool calling to `LLMClient`:** each provider maps tools differently, parallel calls and free-form
  argument objects widen what the model can send, and our schema-validated action already gives a closed set of
  names and one string argument.
- **A node in the processing graph:** the run would hold the invoice lock (decisions wait for the whole
  investigation), and an "Investigate" click on a paused invoice would need a new graph run that drops and recreates
  the pause; the agent would also sit next to the node that writes decisions.
- **Send the email:** out of scope and unsafe; a person decides whether and what to send.
- **Let the model choose the recipient:** an invoice can print an attacker's address.

## Consequences

- The agent cannot change any status: a test runs it with a fake model that asks for `approve_invoice` and shows the
  reply is refused and the invoice, its audit log and its graph thread are unchanged.
- Cost per invoice is bounded (about 8 calls; `cost_cap_usd` stops it earlier), and visible per step.
- The transcript is sent again with each step, so input tokens grow with the steps; fine for 8 steps.
- Without native tool calling, the model cannot see the tools' JSON schemas; their contracts are described in the
  prompt (one argument each), and the MCP server validates the argument again.
- Recorded demo results go stale if the seed data changes; they are regenerated with
  `apps/api/scripts/run_agent.py`.
- The api gains the dependency `mcp` 2.3.0 (client side, ADR-017).

## Update 2026-11-19: history and rulebook tools (R3-4b)

The allow-list grows to ten tools: `get_invoice_history`, `search_similar_invoices` and `search_rulebook` on
`mcp-history` (ADR-017). What changed in the loop:

- **Argument limits in code.** Each tool has a pattern (VAT ID, IBAN, order number, `current`, or a question of 3 to
  200 characters without control characters), matched in full before anything is sent; the schema caps every
  argument at 200 characters. An argument out of shape is a tool error the model sees, counts as a tool call, and
  reaches no server and no embedder. The servers check again.
- **The agent cannot choose an invoice.** `search_similar_invoices` takes the literal `current`; the loop passes the
  investigated invoice's id. The model never sees an id, and the prompt stays the same across runs, which recorded
  replay needs (ADR-019).
- **The api embeds rulebook questions.** For `search_rulebook` the loop embeds the question (task `query`) and sends
  the vector with it. The embedding is a model call with purpose `agent`, so it counts against the per-invoice cost
  cap, the daily budget and the run's totals, and it is shown on the tool step. Without a key, on an error, or with
  an unknown price, the vector is dropped and the server searches by full text.
- **The prompt** names the history and the rulebook as data like any tool result ("past invoices were written by
  suppliers too") and says what each is for. Every result stays inside `<<<UNTRUSTED_TOOL_RESULT>>>`.

Poisoning through retrieval (OWASP ASI06): attack text that passed the scan on an earlier invoice reaches the model
later through the history. The attack set has 10 such cases (ADR-019); the history excludes invoices that failed the
injection check, but that check is heuristic, so the model must hold on its own. The recorded demo runs were made
again with the new prompt and tools.
