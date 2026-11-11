# ADR-002: Boundary between deterministic code and LLMs

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

Invoice processing mixes two kinds of work. Some of it has one correct answer that can be computed:
reading a structured XML invoice, checking that net plus VAT equals gross, finding duplicates, matching
an invoice to a purchase order, comparing a bank account with the verified one. Other parts deal with
unstructured or ambiguous input: a scanned PDF, an unusual exception that needs explaining, or choosing
an account and cost centre based on past bookings.

LLMs are slow, cost money per call, can be wrong in ways that look confident, and can be manipulated by
text hidden in the documents they read. Code is fast, free to run, testable and repeatable. Using an LLM
where code would do makes the system less reliable and harder to audit.

## Decision

**Deterministic code** handles everything that has a computable answer. It always runs, is made of pure
functions, and is unit-tested:

- Parsing XRechnung (UBL and CII) and ZUGFeRD XML.
- Schema and business-rule validation.
- All arithmetic: line totals, VAT, rounding, invoice totals.
- Matching: duplicates, known supplier, bank account against the verified registry, purchase order.

**An LLM is used only in three places:**

1. **PDF and scan extraction**, when there is no structured XML. The output follows a fixed schema with a
   confidence value per field; low confidence forces a human check. Extracted values then go through the
   same deterministic checks as XML values.
2. **Exception reasoning**, only when a check has failed: an agent with read-only tools gathers evidence,
   explains the problem and drafts an email to the supplier.
3. **Booking suggestion**: proposing account, cost centre and tax code from similar approved bookings,
   with the evidence it used.

An LLM never decides whether a check passed, never computes amounts, and never approves anything.
Adding a new LLM step requires a new ADR.

## Alternatives

- **LLM for everything (send the whole invoice to a model):** cheaper to build, but unreliable maths, no
  repeatability, high cost and a large prompt-injection surface.
- **No LLM at all (rules and OCR templates only):** reliable for XML, but breaks on varied PDF layouts and
  cannot explain exceptions in plain language.
- **LLM as a second checker on top of code:** adds cost and disagreement without a clear tie-breaker.

## Consequences

- Most invoices with structured XML are processed with no model call at all, so cost and latency stay low.
- Every check result can be reproduced and explained from code and data.
- The prompt-injection surface is limited to three well-defined steps, which we can test directly.
- Each field records where its value came from (XML or LLM) so reviewers know what to trust.
- We must write and maintain parsers and rules ourselves instead of delegating them to a prompt.
