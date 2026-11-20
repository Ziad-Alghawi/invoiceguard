# ADR-024: Edge to cluster and cluster bootstrap on the demo server

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

ADR-021 puts k3s, Argo CD and sealed-secrets on the demo VPS, and keeps Caddy as the server's edge. Its
2026-11-20 amendment keeps the 4 GB CX23 (no larger server was available at an acceptable price). R4-4 moved the
live demo from Docker Compose onto that cluster. Several details were open until then, and some first plans did
not survive contact with the server:

- **Caddy runs in Docker** on the network `edge`; Traefik runs in k3s. "Localhost" means a different machine in
  each, and k3s's ServiceLB would take ports 80 and 443 from Caddy.
- **Forwarded addresses:** the per-IP login limit (R4-2) needs the visitor's address through Caddy, Traefik and
  web. Traefik keeps `X-Forwarded-For` only from trusted peers; which address it sees for Caddy depends on
  Docker's and k3s's NAT rules.
- **Argo CD core** has no argocd-server, which normally creates the `default` project. Its Ingress health check
  waits for a load-balancer address, which a ClusterIP Traefik never sets.
- **Memory:** 4 GB for the host, Caddy, k3s, Argo CD and the app.
- **Order after a reboot:** Caddy reaches Traefik through Docker's bridge, which exists only once Docker runs.

## Decision

- **Edge:** Caddy stays the only public entry and keeps TLS. Its site forwards to
  `host.docker.internal:8880` (`extra_hosts: host-gateway`, Docker's bridge address 172.17.0.1). Traefik has
  **hostPort 8880 without `hostIP`**: Traefik's chart also uses `hostIP` as the listen address inside the pod,
  where the bridge address does not exist, so Traefik could not start. The port answers on every address of the
  server; the Hetzner Cloud Firewall lets only 22, 80 and 443 in (as for k3s's own 6443 and 10250). ServiceLB is
  off, Traefik's Service is ClusterIP, websecure is not exposed.
- **Forwarded headers:** Traefik trusts `X-Forwarded-For` from **10.42.0.1/32** only. Measured on the server with
  a `whoami` pod, called from inside the Caddy container: Docker masquerades Caddy's requests to the pod network's
  gateway, and the header arrives as `<visitor>, 10.42.0.1`. The api trusts the pod network, walks the header
  from the right and lands on the visitor; the first failed login after the move recorded the real address.
- **Ingress address:** Traefik writes **127.0.0.1** into every Ingress's status (`ingressEndpoint.ip`, with
  `publishedService` off), so Argo CD's Ingress health check can turn Healthy.
- **Boot order:** a systemd drop-in starts k3s after Docker (`After=` and `Wants=docker.service`).
- **Two layers:**
  - The **platform** (k3s, Argo CD core, the sealed-secrets controller) is installed by hand from pinned versions,
    with the release files checked by SHA-256 (`infra/k3s/fetch.sh`), and documented step by step
    (`docs/deploy.md`). The bootstrap files in `infra/argocd/bootstrap/` add the `default` AppProject, the health
    check for child Applications and a repo-server that renders one chart at a time; the applicationset-controller
    is scaled to 0.
  - The **app** comes from git: the root Application (app-of-apps) follows the tag `demo` and syncs in waves:
    the namespace, the SealedSecrets, PostgreSQL, then the app with its PreSync migration hook.
- **Secrets:** the plain values stay on the server (`/opt/invoiceguard/.env`, mode 600) as the source for
  `infra/k3s/seal-secrets.sh`; only sealed values are in git. The script keeps an existing PostgreSQL secret,
  whose passwords the database already uses. The sealing key has a backup off the server, never in git.
- **Operating as `deploy`:** k3s's built-in `kubectl` reads `~/.kube/config` only with `KUBECONFIG` set (in
  `~/.bashrc`); `/etc/rancher/k3s/config.yaml` is mode 644, since it holds no secrets.
- **Tested in CI** on k3d with the server's files (job `helm`): a dry run of the manifests; Argo CD core with the
  bootstrap files reads, renders and compares the three Applications at the commit, without deploying; k3s's
  Traefik is started with `traefik-config.yaml` and must roll out, listen on `:8000`, have hostPort 8880 without a
  host IP and give the Ingress 127.0.0.1. Both tests were first run against the bug they guard against and failed.

## Alternatives

- **Traefik on Docker's bridge address only** (`hostIP`): what the plan said; the chart turns it into a listen
  address that does not exist in the pod.
- **Traefik with `hostNetwork`:** binds where asked, but breaks the NetworkPolicy "only Traefik reaches web"
  and puts Traefik's other ports on the host.
- **A fixed ClusterIP that Caddy reaches through k3s's iptables rules:** nothing listens on a host address, but it
  relies on how Docker's and k3s's rules interact; unusual and hard to explain.
- **Caddy on the host network:** reaches 127.0.0.1, but changes how every other site on the server connects.
- **Argo CD manages itself and sealed-secrets:** one more layer of bootstrap order (the controller must exist
  before anything is sealed); not worth it for one node.
- **The full Argo CD install** (with the UI server, which creates the default project): more memory on 4 GB, and
  a UI that would need its own login and exposure.
- **An Argo CD health override that calls every Ingress healthy:** one line, but it would hide a real missing
  address.

## Consequences

- A merge to `main` reaches the demo without a manual step; a rollback is moving the tag back.
- The firewall is the only layer in front of ports 8880, 6443 and 10250. If it is detached, they are reachable.
- Platform upgrades (k3s, Argo CD, sealed-secrets, Traefik through k3s) are manual and need new pins and hashes;
  Dependabot does not see them.
- The cutover cost about an hour of downtime instead of 10 to 15 minutes, mostly because of the missing default
  project; CI now runs Argo CD on k3d for that reason.
- If Docker's NAT changes (another bridge setup, Docker's nftables backend), the address Traefik sees for Caddy
  may change, and the per-IP limit would count one visitor; the check in `docs/deploy.md` (a failed login must
  show your own address) catches that after any such change.
- Supersedes the hosting part of ADR-014; amends ADR-021 (edge details, bootstrap).
