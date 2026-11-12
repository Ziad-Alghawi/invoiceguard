# ADR-009: KoSIT validator as its own service, called over HTTP

- **Status:** Accepted
- **Date:** 2026-11-12

## Context

German public-sector invoices must conform to XRechnung, a CIUS of EN 16931. Conformance is defined by
an XML Schema plus hundreds of Schematron business rules (`BR-*`, `BR-DE-*`). Our own parser
(ADR-005) only reads the terms we need. It does not check the whole document against these rules,
and we should not write our own version of them.

The reference implementation is the **KoSIT validator** (Koordinierungsstelle für IT-Standards):

- A Java application, published as a standalone jar on GitHub (`itplr-kosit/validator`).
- It is driven by a separately released **XRechnung configuration** (`itplr-kosit/validator-configuration-xrechnung`):
  scenarios, XSDs and compiled Schematron.
- It has a built-in **daemon mode**. It listens on HTTP, takes the invoice XML as a `POST` body and answers with an
  XML report:
  - status `200` when the document is acceptable;
  - status `406` when it is not;
  - status `422` when it cannot read the input.
- `GET /server/health` reports liveness.

Constraints:

- The API is Python (ADR-001), so the validator cannot run in-process.
- KoSIT does not publish an official container image.
- The validator loads its scenarios and Schematron at start-up (about 10 s). After that, a validation
  takes about 0.3 s on the first call and 50-100 ms on later calls (measured locally on the samples).
- The validator is not needed for the other checks (VAT math, IBAN, PO match), and the fraud check must
  never wait for it.

## Decision

Run the official KoSIT validator **unchanged in its own container** (`services/validator`), in daemon mode, and call
it from the API **over HTTP with a timeout**.

Image:
- A multi-stage Dockerfile. An `alpine` stage downloads the validator jar and the XRechnung configuration zip with
  `ADD --checksum=sha256:...`, so a changed or tampered artifact fails the build.
- The runtime stage is `eclipse-temurin:21-jre-noble`. It runs the jar as a non-root user, with a `HEALTHCHECK` on
  `/server/health`.
- Both base images are pinned by digest.
- Versions: validator **1.6.3**, XRechnung configuration **v2026-08-31** (XRechnung 3.0.2). Both were the latest
  releases on 2026-11-12.

Where the hashes come from:
- The SHA-256 values in the Dockerfile are the `digest` fields that GitHub publishes for each release asset
  (`gh api repos/itplr-kosit/validator/releases/tags/v1.6.3`, and likewise for the configuration release).
- We checked them by downloading both files and running `sha256sum`; the results matched.
- KoSIT does not publish separate checksum files.
- To upgrade: change the URL and the hash together, take the new hash from the release's asset digest, check it the
  same way, and run the `kosit` tests.

API side (`checks/kosit.py`):
- A small client posts the XML with Python's `urllib` (no new dependency) and the configured timeout
  (`INVOICEGUARD_VALIDATOR_URL`, `INVOICEGUARD_VALIDATOR_TIMEOUT_SECONDS`, default 20 s).
- It reads only what the check needs from the report: accept or reject, the matched scenario, and the messages
  (level, rule code, text). The report is parsed with the same hardened parser as invoices.
- It does not return the HTML part of the report.

Check results:
- `200` → `passed`, or `warning` when the report has rule warnings.
- `406` with a matched scenario → `failed`, with the rule codes as evidence. The invoice is blocked.
- `406` without a matched scenario → `warning`. The configuration only knows XRechnung and plain EN 16931, so a
  ZUGFeRD BASIC profile, for example, is simply not validated.
- Anything else, including timeouts, refused connections, other status codes or an unreadable report, gives the
  result "no answer". The check is then `skipped` with the reason, and processing goes on.
- An unset URL is skipped the same way.
- The call happens before any database write, so a slow validator never holds row locks.

In Compose the service is called `validator`, and the API does not `depends_on` it. CI runs the `kosit`-marked tests
and the end-to-end smoke test against this Compose service.

## Alternatives

- **Run the jar in the API image (subprocess per invoice):** puts a JRE into the Python image and pays the JVM start
  plus Schematron loading (about 10 s) on every invoice.
- **A small wrapper service around the jar (own Java or Python HTTP layer):** more code to own. The validator's
  daemon already offers the endpoint and a health check.
- **Community container images of the validator:** convenient, but someone else's build of a security-relevant
  component. Building from the release artifacts with pinned hashes is just as little work.
- **Re-implementing the Schematron rules (for example with `lxml.isoschematron` and the XSLT from the
  configuration):** XRechnung's rules need XSLT 2.0/3.0, which lxml (XSLT 1.0) cannot run. We would then be
  maintaining our own validator.
- **Making the validator a hard dependency (a failure blocks the invoice):** an outage would block every invoice,
  and the reviewer would learn nothing new. A `skipped` result is visible on the invoice, and the reviewer can
  re-run processing later.

## Consequences

- One more container: a 430 MB image (JRE plus the configuration) and a JVM sized at `MaxRAMPercentage=75` of its container memory limit.
  In R4 the Helm chart needs a memory limit for it.
- XRechnung updates are a version-and-hash bump in one Dockerfile, verified by the `kosit` tests.
- An invoice processed while the validator is down stays `ready` or `blocked` on the other checks, with a
  `skipped` KoSIT result. There is no automatic re-validation (ADR-007: no retries yet).
- Plain ZUGFeRD profiles (not XRechnung) get a `warning` ("not validated"), not a pass. Validating them needs the
  ZUGFeRD/Factur-X Schematron, which is not part of this configuration.
- Only the first `MAX_MESSAGES` (20) report messages are stored as evidence, plus the total count.
