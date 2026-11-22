# Interview notes

Questions a reviewer or interviewer is likely to ask about InvoiceGuard, with short answers. Every answer comes
from a decision record, a measurement or the development log; the source is named after each answer. Numbers
are from [results.md](results.md) and [status.md](status.md) unless stated otherwise.

## The product

**What problem does it solve?**
German SMEs receive e-invoices (XRechnung, ZUGFeRD) and PDFs, and the expensive mistakes are paying a
fraudulent bank account, a duplicate or more than was ordered. InvoiceGuard checks each invoice against master
data before anyone pays, blocks the suspicious ones, and leaves every decision to a person. It never pays or
posts anything; its output is a DATEV-style booking file for the tax advisor. (README, ADR-003)

**Why not let an LLM do the whole job?**
Most of the work has a computable answer: parsing XML, VAT arithmetic, matching an IBAN against a registry.
Code does that reproducibly and can be unit-tested. An LLM is used in three places only: reading PDFs without
XML, explaining a blocked invoice, and (as retrieval, without a chat model) suggesting a booking account. It
never decides whether a check passed, never computes amounts and never approves. A new LLM step needs a new
ADR. (ADR-002)

**What happens to an invoice, step by step?**
Upload answers `202`; a LangGraph graph per invoice reads it (own XML parser, or the model for a plain PDF),
runs the checks, and pauses at review with `interrupt()`. A decision resumes the thread; only the graph's last
node writes the decision and its audit row, in one transaction. Approved invoices are exported once to DATEV.
(ADR-007, ADR-015)

## Safety

**How do you stop the model from being steered by invoice text?**
Three layers. Invoice text reaches a model only as JSON between labelled markers, never in the system prompt.
A heuristic scan (no LLM) of every XML text and the PDF text layer blocks invoices with instructions to an AI
or hidden Unicode, and such invoices are never sent to the agent. And the agent cannot do harm if it is
steered: its tools are read-only and it has no way to decide. (ADR-002, ADR-017, ADR-018)

**Does the scan work?**
On its own, not well: it flagged 14 of the 44 attack texts in the first attack set, none of the indirect
wordings, French or Turkish. But 0 of 54 attacks succeeded end to end, because the model held on the rest and
the agent cannot act. I did not add an LLM classifier, because no attack got through and ADR-002 asks for a
measured reason before a new LLM step. (results.md, status.md R3-3)

**What stops someone from approving a fraudulent invoice?**
Approval is a pause in the workflow, not a button the UI could skip. A blocked invoice needs four eyes: one
user requests an override with a reason, a different user with the approver role confirms it. The API checks
role and requester, and the graph's decide node checks them again; the requester is read from the audit log.
Self-approval attempts are logged as security events. (ADR-003, ADR-016)

**Why read-only MCP servers instead of letting the agent query the database?**
What the agent can reach is the real safety boundary, because it must be assumed that it can be steered. Each
MCP server logs in with its own PostgreSQL role that may only `SELECT` its own tables or views; the registry
server sees four supplier columns. Tests run as each role (`SET ROLE`) and assert `InsufficientPrivilege` on
everything else. (ADR-017; development log 2026-11-19: a privilege test once passed for the wrong reason, a
view that was not updatable anyway, so the tests now assert the exact error class.)

**Why an own agent loop and not LangGraph's prebuilt ReAct agent?**
The prebuilt agent needs provider tool calling through LangChain's model classes instead of our `LLMClient`,
which logs cost and checks prices, and its recursion limit covers neither cost nor tool-call counts. The own
loop asks for one schema-validated JSON action per step, with a closed list of tool names and a pattern per
argument checked in code, and stops at 8 steps, 12 tool calls, 90 s or $0.05 per invoice. It runs outside the
approval graph, so it holds no lock and cannot resume or approve anything. (ADR-018)

**Who receives the agent's email?**
Nobody automatically: it is a draft for a person. The recipient comes from the supplier master data, never
from the invoice, because an invoice can print an attacker's address. (ADR-018)

**What about poisoning through retrieval?**
Only approved invoices that did not fail the injection check enter the booking history and the index, and the
agent reads them through views. Ten attack cases put injected text into the history: the agent delivered it
to the model 0 times on its own (it rarely reads the history), so I forced the history call in the eval: 10 of
10 delivered, 0 followed. The first number tested nothing, which is why the eval now measures delivery before
counting a defence. (ADR-018, ADR-020, status.md R3-4b)

## Measurement

**How do you know the extraction is good?**
An eval harness runs the app's real code on pinned public data (KoSIT testsuite, ZUGFeRD corpus) and generated
German invoices, with recorded model replies, so CI replays it for free. At reasoning effort `low`,
`gemini-3.8-flash` gets 99.2 % of document terms right on completed extractions, at $0.0058 per invoice. The
CI gate fails a pull request on a drop of more than 2 points, any successful attack, or 25 % more cost. A
deliberate regression on a throwaway branch failed it. (ADR-019, results.md)

**Why reasoning effort `low`?**
Measured: the default thinking level wrote about twice as many output tokens as input, about half of it
thinking. At `low` the cost and latency fell by about half. On the eval set, `medium` and `high` read about the
same (99.4 % and 99.6 % of document terms against 99.2 %) at 2.2 and 3.8 times the cost, and timed out more
often. (ADR-010, development log 2026-11-12, results.md)

**Is the model's confidence useful?**
Less than hoped. At `low`, 8 of 9 wrong fields had a confidence of 0.8 or more; the errors cluster between 0.8
and 0.9, so the threshold moved to 0.9, which flags 5 of the 9. On ten cases with two conflicting printed
values, the model chose the right one every time but never lowered its confidence. Confidence measures how
sure the model is about what it read, not whether the document is consistent. (results.md, status.md R3-2)

**Why did you keep the more expensive model?**
gemini-3.5-flash-lite costs less per token but wrote more thinking tokens and needed a retry, so it was
$0.0050 per invoice against $0.0053, made one confident error, and was faster. Pro cost almost five times as
much without being more accurate. Compare models on cost per task, not on the price list. (ADR-026)

**What did the eval find that the tests did not?**
Two things. A valid KoSIT invoice "not subject to VAT" (category O) failed the VAT check, which would have
blocked a correct invoice. And a deliberate regression that compared only the bank code of an IBAN passed every
unit test, because no test had a changed account at the same bank, the common fraud case; the eval's fraud set
caught it, and a unit test for it followed. (development log 2026-11-18 and 2026-11-19)

## Platform

**How does a change reach the demo?**
CI runs lint, types, tests, the Playwright tests on Docker Compose and a Helm install on k3d, scans the images
with Trivy and pushes them to GHCR. After every job of a `main` commit passes, CI moves the git tag `demo`;
Argo CD on the server follows that tag and syncs the Helm charts, with the migration as a PreSync hook. One
measured merge took 3 min 49 s from tag to sync. (ADR-021, ADR-024, status.md R4-4)

**Why k3s on a 4 GB server and not managed Kubernetes?**
Budget. An 8 GB server was not available at an acceptable price, so the cluster was sized from measurements
(about 2.3 GiB at idle) with kubelet reservations, small limits and Argo CD core without its UI. Prometheus
runs on the server; Grafana runs on my machine through an SSH tunnel. (ADR-021, ADR-025, development log
2026-11-20)

**What went wrong during the cutover?**
Argo CD core has no `default` project (argocd-server creates it, and core has none), so nothing synced for
about ten minutes of downtime. Later, a Traefik config file outside GitOps blocked a sync wave, because Argo
CD starts a wave only when the earlier ones are healthy. Both are now covered: the bootstrap adds the project,
and CI waits for every app to be Synced and Healthy on k3d. (development log 2026-11-20 and 2026-11-21)

**How is the database protected from the app itself?**
The api logs in as `invoiceguard_app`, which may only read and insert on the audit, security and model-call
logs, cannot truncate them, has no DDL and owns nothing. Migrations run as a separate step; in Kubernetes as an
owner that is no superuser (local Compose still migrates as the image's superuser). (ADR-022, ADR-023)

**How do you handle supply-chain risk?**
Dependencies are pinned with hashes, every GitHub Action is pinned to a commit SHA, images are scanned by
Trivy, and a release must be public for at least a week before an upgrade (ADR-004, after two compromised
LiteLLM releases in March 2026). The rule held when a task list asked otherwise: the LiteLLM upgrade waits for
its date, and three transitive packages of next-intl were pinned to older releases. Pinning a package does not
pin its data either: LiteLLM downloaded its price table from GitHub on import until that was switched off.
(ADR-004, ADR-027, development log 2026-11-12)

## Mistakes and lessons

**Tell me about a bug that was hard to find.**
A retried approval would have resumed nothing. After a failed decide step, LangGraph had already saved the
checkpoint after `review`, so the thread was no longer paused, and `Command(resume=...)` on a thread that is
not paused returns without doing anything. The endpoint now checks that the thread is paused at review before
resuming, and the decide node refuses a decision whose status before no longer matches. (development log
2026-11-16, ADR-015)

**And a flaky test?**
Two extraction tests failed in CI, a different one each run, on a PR that changed no Python. Startup recovery
only tries each invoice's lock; it read a fresh upload and released the lock, the upload's own run then found
the invoice already read and returned early, and recovery's extraction skipped the held lock. Each side assumed
the other would finish. A run whose claim fails now still checks for extraction, and two deterministic tests
reproduce the race without threads. (development log 2026-11-20, issue #31)

**What would you do differently?**
Check what a dependency does on import, earlier: LiteLLM loaded the nearest `.env` and put a real API key into
the test settings. Classify UI text by who writes it, not by where it is stored: the German UI showed "Failed
checks: po_match." from the API until the API sent a code with it. And run end-to-end tests against a used
database, not only a fresh CI one, because that is where hidden assumptions show. (development log 2026-11-12,
2026-11-14 and 2026-11-22; ADR-027)

**What are the honest limits?**
It is a demo with made-up data, not a product: no backups, not a certified DATEV interface, purchase-order
lines matched by position, self-reported model confidence, small and generated eval sets, and a heuristic
injection scan. The README lists them all. (README, status.md)
