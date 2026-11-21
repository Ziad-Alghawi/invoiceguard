# ADR-025: Metrics with one small Prometheus on the demo, Grafana on the developer machine

- **Status:** Accepted
- **Date:** 2026-11-21

## Context

R4-5 adds metrics to the demo (PLAN.md §7): requests, latency, errors, invoices processed, check
results, review decisions, LLM calls and cost, plus alerts for the error rate, the cost cap and the
validator. The demo runs on one 4 GB server (ADR-021) with about 1.3 to 1.4 GB available at idle.
The gate for this work is 1.0 GB available, so monitoring may use about 300 MB at most, and less is
better: the validator and the api need room when invoices are processed.

The full kube-prometheus-stack (operator, Alertmanager, node-exporter, kube-state-metrics, Grafana)
was cut from R4 for this reason (status.md). Nothing may be public: the demo's only entry is Caddy,
and metrics are not for visitors.

## Decision

**The api exposes `GET /metrics`.** It uses the official `prometheus-client` library, with its own
registry per app and no `_created` series. The counters are per process, and Prometheus sums the
pods.

- **HTTP:** a small ASGI middleware counts requests and their duration by route template, so the
  number of series stays fixed. `/metrics`, `/health` and `/ready` are not counted.
- **Business counters:** a listener on the app's session factory counts the rows each transaction
  commits: audit events (processed invoices by outcome, decisions by action), check results,
  security events and model calls (calls, cost, tokens, latency). A rolled-back write is never
  counted, and the writers need no metrics code.
- **Agent runs** are counted where they end. **KoSIT calls** are counted in the validator client.
- **Validator health:** `invoiceguard_validator_up` checks the validator's health endpoint at each
  scrape, so a down validator shows even when nobody uploads.
- **Labels** are fixed vocabularies (route templates, statuses, check types, models), never invoice
  data. A test checks this.

**Prometheus v3.16.0, alone, runs on the demo.** It comes from its own small chart
`infra/helm/invoiceguard-monitoring`, deployed by Argo CD like the app (sync wave 3).

- **Scraping:** every 30 s. Targets come from DNS service discovery on a headless api Service, so
  every api pod is scraped. This needs no RBAC and no ServiceAccount token.
- **Retention:** 7 days with a 300 MB cap, on a 1 Gi local-path volume.
- **Memory:** `GOMEMLIMIT=150MiB`, request 96 Mi, limit 192 Mi.
- **Network:**
  - no Ingress;
  - a NetworkPolicy lets nothing in and lets Prometheus out to the api pods and DNS only;
  - the api's policy lets Prometheus in on port 8000.
- **Alert rules** (5xx share, cost cap or daily budget reached, validator down, api not scraped)
  live in `files/rules.yml`. `promtool test rules` makes each one fire in CI. There is no
  Alertmanager: firing alerts show on Prometheus's `/alerts` page and in the dashboard.

**Grafana runs on the developer machine** (`make grafana`, `infra/grafana/`), with the datasource
and the dashboard JSON provisioned from the repo. It reads Prometheus through
`ssh -L 9090:… 'kubectl port-forward …'` (docs/deploy.md).

## Alternatives

- **Prometheus and Grafana both on the server:** about 100 to 150 MB more for Grafana, putting the
  idle margin close to the 1.0 GB gate for a UI used a few minutes a week.
- **VictoriaMetrics single node with vmalert:** lighter (about 40 to 75 MB together) but two
  components, and less standard than Prometheus, which the plan names. Prometheus measured small
  enough (see Consequences).
- **kube-prometheus-stack or the community Prometheus chart with its parts switched off:** an
  operator or ClusterRoles, a reloader sidecar and many values to audit. Our own chart is about 100
  lines, like the PostgreSQL chart (ADR-023).
- **Business numbers from SQL queries at scrape time:** they would survive restarts, but every pod
  would report the same totals, the nightly reset would make them jump, and they add database load
  per scrape. Counting committed rows in process is the standard model.
- **Counting calls in each writer:** about twelve call sites in business code instead of one
  listener, and easy to forget in a new writer.
- **A separate metrics port on the api:** nothing outside the cluster reaches the api (web forwards
  fixed paths only), and the NetworkPolicy already limits who reaches port 8000.

## Consequences

- **Memory on k3d (k3s v1.36.6), 2026-11-21,** with the demo samples, about 500 api requests and 10
  minutes of scrapes:
  - Prometheus: 31 to 37 MiB working set (what `kubectl top` and the kubelet count), 94 MiB RSS with
    the mapped TSDB files;
  - 901 series in total, 89 samples per api scrape, 6 ms per scrape (validator health check
    included);
  - the api with metrics: 126 to 128 MiB, against 129 to 130 MiB for the `main` image under the same
    traffic, so no measurable cost.

  On the server after the first deploy (2026-11-21): Prometheus at 30 Mi, and `available` at
  1,245 MB against 1,320 MB before it (details in status.md).
- **Counters restart at 0 with an api restart.** `rate()` and `increase()` handle that.
  - A series created by its first event cannot show that event in `increase()`. So the two
    cost-cap series start at 0.
  - The 5xx share needs a few minutes of errors to fire, which is the point of the alert.
- **Rows committed by other processes are not counted:** the nightly demo reset CronJob and the
  migration hook. The dashboard shows visitor and reviewer activity, not the reset's six samples.
- **The demo has no model key (ADR-010),** so the LLM panels stay at 0 there. Tests cover them with
  the fake client.
- **No one is notified when an alert fires;** someone has to look. Alertmanager with a mail or chat
  receiver is the next step if the demo ever matters at night.
- **Grafana needs the tunnel.** When the developer machine is off, Prometheus still records and
  evaluates the rules, and its UI is reachable through the same port-forward.
- **Upgrades:** the Prometheus and Grafana images are pinned by digest and upgraded by hand, like
  the platform (ADR-024).
