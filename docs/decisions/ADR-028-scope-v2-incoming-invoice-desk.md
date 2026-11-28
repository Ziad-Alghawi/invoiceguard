# ADR-028: Scope v2.0: an incoming-invoice desk

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

v1.0.0 (R0 to R5) is an invoice checker: an invoice is uploaded, read (XML by code, PDF by an LLM),
checked, and a person approves or rejects it before a DATEV-style export. An accounts-payable team
needs more than that every day:

- Invoices arrive by email, not by upload: 96 % of German companies receive invoices by email
  (Bitkom), and PDFs are still the majority. Valid e-invoices were about 7 % of incoming invoices in
  spring 2025.
- Receiving e-invoices is mandatory since 1 January 2025. The recipient has to check an invoice's
  correctness before deducting input VAT, and the BMF names three error classes: format errors (not an
  e-invoice), business-rule errors and content errors (input VAT at risk even when the validator
  passes).
- Money is lost on time, not only on fraud: XRechnung carries Skonto terms in BT-20, and 2 % for
  paying 20 days early is about 37 % a year.
- Since 9 October 2025 banks compare payee name and IBAN (Verification of Payee); after a "no match"
  the payer is liable, so a changed IBAN needs a real workflow, not only a warning.

## Decision

Version 2.0 turns InvoiceGuard into an **incoming-invoice desk** for a German SME with about 400
invoices a month: every invoice arrives by itself (mailbox or upload), is read, checked against the tax
rules and fraud signals, routed to the right approver before its Skonto date, and leaves as a DATEV
booking file, a payment proposal list and an archive record. Humans decide.

- **AI reads and writes text; code decides.** A model is used only where the input is unstructured
  text: sorting mails that rules cannot place, reading PDFs and scans, the exception agent's finding
  and supplier email draft, and later question answering. Validation, fraud signals, matching, Skonto,
  routing and learned rules are code. No model sets a status, a score or a decision (ADR-002 still
  holds).
- **A payment proposal file is allowed, a payment is not.** v2 may write a list of approved invoices to
  pay (CSV, Skonto first, IBAN from the verified registry, never from the invoice). A person pays in
  their own bank. There is still no tool that pays, posts, writes to an ERP or the registry, or sends
  mail by itself (ADR-003); outbound supplier mail goes out only after a person clicks Send.
- **n8n is dropped.** The inbox lives inside the application, so InvoiceGuard stays the one system of
  record with one audit log, and the untrusted-content rules apply to mail in the same code.
- **The Arabic UI is dropped.** The UI stays German (default) and English (ADR-027).
- Work is cut into phases P0 to P5, each ending at a gate with numbers. The first, P1 "Review you can
  trust", makes the review itself faster and checkable: split view, click-to-highlight, readable
  XRechnung, keyboard shortcuts.

Non-goals stay: no real customer data, no bank connection, no outgoing invoices or Peppol access
point, no certified DATEV interface, no multi-tenant SaaS, no model training.

## Alternatives

- **Polish v1 only:** fewer risks, but a checker without an inbox, tax-rule classes or Skonto does not
  match how an AP team works, which is the product goal.
- **n8n for mail intake:** quick to wire up, but a second system with its own state, credentials and
  logs, and the untrusted mail text would cross a boundary we do not control.
- **Arabic UI:** right-to-left layout and a third message file for a market the project does not
  target.
- **Real payments (EBICS, PSD2):** a regulated integration and liability that a demo must not carry; a
  proposal file gives the same review value.

## Consequences

- New data and services follow in later ADRs (job queue and worker, mail inbox, archive record,
  tax-rule check, bank change workflow, approval routing, learned supplier rules), each with its own
  eval set and gate.
- The safety rules grow with the inbox: mail bodies, headers and attachments are untrusted data like
  invoice text, and the attack set must cover them.
- The 4 GB demo server stays the limit: every phase checks the memory budget before it is deployed.
- The total model budget for v2 is under $3; recorded replies keep CI free.
