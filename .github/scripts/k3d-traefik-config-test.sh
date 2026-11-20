#!/usr/bin/env bash
# Applies the server's Traefik settings (infra/k3s/traefik-config.yaml) to k3s's own Traefik on the
# k3d cluster and checks that Traefik starts with them (ADR-024). k3s's helm-controller merges the
# HelmChartConfig into its bundled chart exactly as on the server, so a setting the chart turns
# into a bad flag fails here, not on the server.
#
# Used by the CI job `helm` as its last step: the Service becomes ClusterIP, so k3d's load balancer
# no longer reaches Traefik afterwards.
set -euo pipefail

ks() { kubectl --namespace kube-system "$@"; }
args() { ks get deployment traefik --output jsonpath='{.spec.template.spec.containers[0].args}'; }

ks apply --filename infra/k3s/traefik-config.yaml

echo "--- k3s's helm-controller upgrades Traefik with the settings"
for attempt in $(seq 1 90); do
  [[ $(args) == *'--entryPoints.web.forwardedHeaders.trustedIPs='* ]] && break
  [ "$attempt" -lt 90 ] || { echo "Traefik was not upgraded with the settings"; exit 1; }
  sleep 2
done
ks rollout status deployment/traefik --timeout=180s

echo "--- The web entrypoint listens on the pod's own addresses"
[[ $(args) == *'"--entryPoints.web.address=:8000/tcp"'* ]] || {
  echo "unexpected web entrypoint: $(args)"; exit 1; }

echo "--- hostPort 8880 without a host IP"
web=$(ks get deployment traefik \
  --output jsonpath='{.spec.template.spec.containers[0].ports[?(@.name=="web")]}')
echo "$web"
[[ $web == *'"hostPort":8880'* && $web != *hostIP* ]]

echo "--- The Service is ClusterIP and does not expose websecure"
test "$(ks get service traefik --output jsonpath='{.spec.type}')" = ClusterIP
if ks get service traefik --output jsonpath='{.spec.ports[*].name}' | grep -q websecure; then
  echo "websecure is exposed"; exit 1
fi

echo "--- Ingresses get 127.0.0.1 as their address (Argo CD's Ingress health needs one)"
[[ $(args) == *'"--providers.kubernetesingress.ingressendpoint.ip=127.0.0.1"'* ]]
[[ $(args) != *publishedservice* ]]
for attempt in $(seq 1 30); do
  address=$(kubectl --namespace invoiceguard get ingress invoiceguard \
    --output jsonpath='{.status.loadBalancer.ingress[0].ip}')
  [ "$address" = 127.0.0.1 ] && break
  [ "$attempt" -lt 30 ] || { echo "the Ingress has no address: '$address'"; exit 1; }
  sleep 2
done
