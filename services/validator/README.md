# services/validator
The official KoSIT validator (Java) with the XRechnung configuration, in a container. The API sends it each
invoice's XML over HTTP. Design and reasons: [ADR-009](../../docs/decisions/ADR-009-kosit-validator-service.md).

| | |
| --- | --- |
| Validator | [itplr-kosit/validator](https://github.com/itplr-kosit/validator) 1.6.3 (standalone jar) |
| Configuration | [validator-configuration-xrechnung](https://github.com/itplr-kosit/validator-configuration-xrechnung) v2026-08-31 (XRechnung 3.0.2) |
| Visualization | [xrechnung-visualization](https://github.com/itplr-kosit/xrechnung-visualization) v2026-10-13 (XRechnung 3.0.2), stylesheets only ([ADR-029](../../docs/decisions/ADR-029-document-viewer-and-xrechnung-visualization.md)) |
| Runtime | `eclipse-temurin:21-jre-noble`, non-root user `kosit`, ports 8080 (validator) and 8082 (visualization) |

The [Dockerfile](Dockerfile) downloads both release artifacts with `ADD --checksum=sha256:...`, so the build fails
if either file differs from the pinned version. The hashes are the SHA-256 digests GitHub publishes for each
release asset, checked against our own download (see ADR-009 for how to upgrade).

## HTTP interface (KoSIT daemon mode)
| Request | Answer |
| --- | --- |
| `POST /` with the invoice XML as body | XML report; `200` acceptable, `406` not acceptable (also when no scenario matches), `422` unreadable input |
| `GET /server/health` | `200` with status `UP` (used by the Docker healthcheck) |
| `POST /visualize?lang=de` (port 8082; `lang=en` for English) | the KoSIT HTML view; `415` not a UBL or CII invoice, `413` above 10 MiB, `422` unreadable XML or a DTD |
| `GET /health` (port 8082) | `200` `UP` |

The visualization runs in the same JVM: `src/invoiceguard/validator/Main.java` compiles the stylesheets with the
Saxon inside the validator jar, starts its HTTP server, then hands the arguments to the official daemon.

The report lists the matched scenario (for example `EN16931 XRechnung (UBL Invoice)`) and one `rep:message` per
finding with `level` (`error`, `warning`, `information`) and the rule `code` (for example `BR-CO-15`).

## Run
In the stack: `make dev` from the repo root (Compose service `validator`, host port `127.0.0.1:8081`). On its own:

```sh
docker build -t invoiceguard-validator services/validator
docker run --rm -p 127.0.0.1:8081:8080 invoiceguard-validator
curl -X POST --data-binary @apps/api/tests/fixtures/ubl_xrechnung.xml http://127.0.0.1:8081/   # 200
```

Start-up takes about 10 s, because the scenarios and Schematron are loaded before the healthcheck passes. After that,
a validation of the sample invoices takes about 0.3 s on the first call and 50-100 ms on later calls (measured
locally).
