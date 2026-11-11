# ADR-004: Model router with LiteLLM

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

InvoiceGuard calls language models in three bounded places (ADR-002): PDF extraction, exception
reasoning and booking suggestions. It needs to talk to at least three kinds of provider:

- **Google Gemini** on the free tier, for the public demo and for PDF extraction, because it reads PDFs
  directly and costs nothing within the free quota.
- **Ollama** on a local machine, for bulk evaluation runs that would burn through a free API quota.
- **An EU-hosted OpenAI-compatible endpoint**, so a German company could keep invoice data in the EU.

The total LLM budget for the project is about €20, and every call must be logged with model, tokens,
cost and latency, with a per-invoice and per-day cost cap that stops processing. Switching a step from
one provider to another must be a configuration change, not a code change, so the same evaluation can
be run against several models and compared.

Two ways to get there: use LiteLLM, an open-source library that exposes one `completion()` call for
100+ providers, or write a thin adapter of our own around the providers' HTTP APIs.

## Decision

Use the **LiteLLM Python SDK** (not its proxy server) behind a small interface of our own.

- Application code depends on our own `LLMClient` protocol with one method per kind of call (structured
  output, chat with tools). Only the implementation of that protocol imports LiteLLM. This keeps the
  library at the edge and makes a later swap a one-file change.
- Cost comes from LiteLLM's built-in price table (`completion_cost`). Our code writes one `model_calls`
  row per call and enforces the cost caps; LiteLLM does not decide whether to stop.
- Model per step is set in environment variables, with LiteLLM model strings such as
  `gemini/<model>` or `ollama/<model>`.

**Default models:**

| Step | Default | Why |
| --- | --- | --- |
| PDF extraction | Current Gemini Flash model on the free tier | Native PDF input, structured output, free quota |
| Bulk evaluations | A local Ollama model | No quota and no cost, so evals can run often |
| Demo and final eval numbers | Gemini Flash | Same model the demo uses |

Gemini model IDs change often (several Flash generations and preview IDs within one year), so the exact
ID is not fixed in this ADR. It is chosen from the Gemini models list when the extraction step is built
and stored in env config. The local Ollama model is chosen the same way, based on what runs on the
development machine; the R4 model comparison may change both defaults.

**Supply-chain guard.** In March 2026 two LiteLLM releases on PyPI (1.82.7 and 1.82.8) were published
with a credential-stealing payload after the maintainers' publishing token was stolen. LiteLLM also
ships several releases a day and pulls in many dependencies. Therefore:

- The version is pinned exactly and installed from `uv.lock`, which stores package hashes.
- Upgrades are deliberate: a pull request that names the new version, after it has been public for at
  least a week, with the changelog read and CI green.
- Only the SDK is installed, not the `proxy` extra.

## Alternatives

- **Own thin adapter:** Gemini, Ollama and most EU hosts all offer an OpenAI-compatible endpoint, so an
  adapter over the `openai` SDK plus a small price table would work and has fewer dependencies. Not
  chosen because we would maintain prices, provider quirks (PDF input, structured output, tool calls)
  and error mapping ourselves, which is not what this project is meant to show. It stays the fallback
  if LiteLLM causes trouble; the `LLMClient` interface makes that swap small.
- **LiteLLM proxy server:** central budgets and keys for many teams; one more service to run and secure
  for a single application.
- **LangChain chat model classes:** we use LangGraph, but a model class per provider still needs its
  own cost tracking and gives a less uniform interface across providers.

## Consequences

- Moving a step between Gemini, Ollama and an EU endpoint is an env change, which the R4 model
  comparison depends on.
- Cost tracking works out of the box, but LiteLLM's price table can lag behind new models; a missing
  price must be treated as an error, not as zero cost, so the cap cannot be bypassed.
- We accept a large dependency with a recent supply-chain incident, and limit the risk with exact pins,
  lockfile hashes and slow, reviewed upgrades.
- Free-tier quotas are low and can change without notice; bulk work must go to Ollama, and the demo must
  show a clear message when the quota is used up.
