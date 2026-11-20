# ADR-021: Platform: k3s on the demo VPS, Helm, Argo CD and GHCR images

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

R4 (PLAN section 11) moves the demo from Docker Compose on one VPS (ADR-014) to Kubernetes, with GitOps:
a commit to `main` reaches the demo without a manual step. PLAN section 8 names Helm, Argo CD, GHCR
images, Trivy and sealed secrets, and it originally named a managed cluster.

Forces:

- **Budget** (PLAN section 3: free or near-free): the demo VPS costs about €6 a month. A managed cluster
  costs its nodes plus a load balancer, several times that.
- **One shared server** (ADR-014): Caddy in `/opt/edge` serves other sites on the same VPS; they must keep
  working and keep their certificates.
- **Memory**: the Compose stack uses about 2.5 GB (the validator's JVM alone has a 1 GB limit). k3s, Argo CD
  and Prometheus/Grafana add an estimated 2 to 2.5 GB; the CX23's 4 GB is not enough.
- **Authorship** (CLAUDE.md): commits show Ziad only, so CD must not commit image tags as a bot.
- **Supply chain**: in March 2026 most tags of `aquasecurity/trivy-action` and `setup-trivy` were rewritten
  to malicious commits (CVE-2026-33634). A tag names whatever its owner (or an attacker) points it at.
- **Time**: 12 to 15 hours a week; operating the platform must not become the project.

## Decision

Run **k3s with one node on the existing VPS**, deployed by **Argo CD from a Helm chart in the repo**, with
images built, scanned and pushed by CI.

- **Server**: rescale the VPS from CX23 to CX33 (8 GB) with "CPU and RAM only", so the disk keeps its size
  and a downgrade stays possible; about €9 a month net with IPv4 instead of about €6 (prices after Hetzner's
  June 2026 change). Done right before the cluster moves in (R4-4), not earlier.
- **Edge**: Caddy stays the server's edge and keeps TLS for every site. k3s's bundled Traefik listens on a
  port bound to localhost, and Caddy forwards `invoiceguard.ziadalghawi.com` to it. No cert-manager.
  Traefik because k3s ships it and ingress-nginx is retired.
- **Images** (R4-1): CI builds the six images, scans each with Trivy (fixable HIGH and CRITICAL findings fail;
  accepted ones in `.trivyignore` with a reason and an expiry date) and pushes them to GHCR on `main`,
  tagged with the full commit SHA. The packages are public, so the cluster pulls without a secret.
- **CI pins**: every GitHub Action is pinned to a full commit SHA, Dependabot updates the pins, and a CI job
  fails on an unpinned action. Trivy runs from its own image pinned by digest, not through an action.
- **CD**: Argo CD (core install: no UI server, Dex or notifications) follows the git tag `demo`. After the
  images of a `main` commit are pushed, CI moves `demo` to that commit. The chart takes the image tag from
  Argo CD's `$ARGOCD_APP_REVISION`, so the deployed commit and the image tag are the same SHA, and no
  commit is needed to deploy.
- **Migrations**: Alembic runs as an Argo CD PreSync Job with the database owner role (it also creates the
  MCP roles, ADR-017); the api runs with a role that has data rights only (R4-2).
- **Secrets**: sealed-secrets; only sealed values are in git.
- **Database**: PostgreSQL stays in the cluster as a StatefulSet with a local volume; no backups, as before
  (sample data, reset nightly; the reset becomes a CronJob).
- **Cut from R4**: self-hosted Langfuse (its v3 needs ClickHouse, Redis and object storage; `model_calls`
  already records cost and latency per call), n8n, paid EU model endpoints and large Ollama models, and the
  full kube-prometheus-stack (Prometheus and Grafana run alone, R4-5).

## Alternatives

- **Managed Kubernetes** (OVH, Hetzner via a provider): real control plane, but nodes and a load balancer
  cost several times the VPS, and the other sites would need their own home.
- **Stay on Compose**: cheapest and already working, but no Helm, GitOps or probes to show, which is R4's
  point.
- **kind or k3d locally only**: free, but nothing public; kept as the local test target for the chart.
- **Traefik as the edge with cert-manager**: one proxy less, but every other site on the server would move
  into the cluster or lose its proxy.
- **Bot commits that bump the image tag** (or Argo CD Image Updater): a common pattern, but commits by
  someone other than Ziad, or one more controller to run; moving a tag needs neither.
- **`trivy-action`**: convenient, but its tags were the attack's way in; the pinned image does the same job.

## Consequences

- A merge to `main` deploys itself; rolling back means moving the `demo` tag to an earlier commit.
- One node is still a single point of failure; probes and restarts make the pods sturdier, not the server.
- The api may now run in more than one pod, so startup recovery and decisions need cross-pod locking
  (R4-2) before the replica count goes above one.
- Each new GHCR package starts private: after the first push, set the six packages to public once in
  GitHub's package settings.
- Ignored Trivy findings expire, so the scan fails again unless the fix arrives or the entry is renewed with
  a new reason.
- Caddy and Traefik are two proxies in a row: request limits (body size) are set in both, and the api must
  trust forwarded client addresses from the proxies only (R4-2, per-IP login limit).
- Supersedes the hosting part of ADR-014 once R4-4 is live; until then the demo runs on Compose.

## Amendment (2026-11-19, R4-3)

- **Migrations:** the Job is a Helm `pre-install`/`pre-upgrade` hook, which Argo CD runs as PreSync, so
  `helm install` and Argo CD run it the same way.
- **Database:** PostgreSQL has its own chart (`infra/helm/invoiceguard-postgres`), installed before the app
  chart, because a hook runs before anything else in its release exists. In R4-4 the two charts become two
  Applications in sync waves. Details in [ADR-023](ADR-023-helm-chart-and-postgres.md).

## Amendment (2026-11-20, R4-4): k3s on the existing 4 GB server

- **Why:** a CX33 cannot be rescaled to in Nuremberg, and no 8 GB server in an EU location is available at
  an acceptable price (CX33 and Arm unavailable, the dedicated 8 GB type about $50 a month). The demo stays
  on the CX23 `invoiceguard` (2 vCPU, 4 GB, 2 GB swap) and k3s goes onto it.
- **The 4 GB estimate above assumed Compose and k3s side by side.** They do not run together: Compose stops
  before the app starts in k3s. Expected memory at idle, about 2.3 GiB of 3.7:

  | Part | MiB |
  | --- | --- |
  | Ubuntu, Docker and Caddy | 290 |
  | k3s (server, containerd, CoreDNS, Traefik, metrics-server, local-path) | 765 |
  | Argo CD core (applicationset-controller scaled to 0) and sealed-secrets | 285 |
  | The app as measured under Compose (validator 445, api 162, web 138, MCP 3 × 80, PostgreSQL 63) | 1,050 |

  The deploy hook, the nightly reset Job and Helm rendering add up to about 550 MiB at peaks, the validator's
  heap up to about 300 MiB more under load.
- **Settings for the small node:**
  - kubelet `system-reserved` 300 Mi, `kube-reserved` 600 Mi and a hard eviction at 200 Mi available, so a
    pod is evicted before the server runs out of memory (`infra/k3s/config.yaml`);
  - the 2 GB swap stays (k3s starts the kubelet with `failSwapOn: false`; pods do not swap);
  - Argo CD core only, the applicationset-controller scaled to 0, and the repo-server renders one chart at a
    time;
  - PostgreSQL's memory limit is 512 Mi on the demo (set in its Application).
- **Gates:** with k3s, Argo CD and sealed-secrets installed and Compose still running, at least 1.2 GB must
  be available, or the move stops; after the cutover the real numbers are compared with the table.
- **Cutover on the same server:** back up the database (full and data-only dumps) and the uploads, copy the
  backup off the server, stop Compose, start the app through Argo CD, restore the data and point Caddy's
  site at Traefik. About 10 to 15 minutes of downtime. Rollback: stop k3s and start Compose again from its
  kept volumes; they are deleted three days after the cutover.
- **Consequences:**
  - No new address, no DNS change, no extra cost (about €6 a month stays).
  - The "rescale right before R4-4" step and its downgrade path are gone.
  - About 1.4 GiB stays free at idle. Prometheus and Grafana (R4-5) need an estimated 250 to 350 MiB, so
    their retention and scrape intervals are chosen for this node in R4-5.
  - A reboot test runs before and after the cutover: k3s starts after Docker, whose bridge address carries
    Traefik's port.
