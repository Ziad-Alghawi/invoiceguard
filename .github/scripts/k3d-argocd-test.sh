#!/usr/bin/env bash
# Bootstraps Argo CD core on the k3d cluster as on the server (docs/deploy.md) and lets it read,
# render and compare the root app and both chart Applications at this commit (ADR-024). A missing
# project, a wrong path or revision, or a chart Argo CD cannot render shows up as a condition.
# The Applications are applied without their sync policy, so Argo CD deploys nothing: the smoke
# test's release already runs in the namespace, and a pull request's images are not in GHCR.
#
# Usage: .github/scripts/k3d-argocd-test.sh <directory from infra/k3s/fetch.sh> <git revision>
set -euo pipefail

platform=$1
revision=$2
a() { kubectl --namespace argocd "$@"; }

echo "--- Argo CD core and the bootstrap files, as on the server"
kubectl create namespace argocd --dry-run=client --output yaml | kubectl apply --filename - > /dev/null
a apply --server-side --force-conflicts --filename "$platform/argocd-core-install.yaml" > /dev/null
a patch configmap argocd-cm --type merge --patch-file infra/argocd/bootstrap/argocd-cm-patch.yaml
a patch configmap argocd-cmd-params-cm --type merge \
  --patch-file infra/argocd/bootstrap/argocd-cmd-params-patch.yaml
a scale deployment argocd-applicationset-controller --replicas 0
kubectl apply --filename infra/argocd/bootstrap/default-project.yaml
a rollout restart deployment argocd-repo-server
a rollout status deployment argocd-repo-server --timeout=180s
a rollout status statefulset argocd-application-controller --timeout=180s

echo "--- The Applications at $revision, without sync: Argo CD reads, renders and compares"
for file in infra/argocd/root.yaml infra/argocd/apps/invoiceguard-postgres.yaml \
  infra/argocd/apps/invoiceguard.yaml infra/argocd/apps/invoiceguard-monitoring.yaml; do
  yq ".spec.source.targetRevision = \"$revision\" | del(.spec.syncPolicy)" "$file" \
    | kubectl apply --filename -
done
for app in root invoiceguard-postgres invoiceguard invoiceguard-monitoring; do
  for attempt in $(seq 1 60); do
    conditions=$(a get application "$app" --output jsonpath='{.status.conditions[*].message}')
    [ -z "$conditions" ] || { echo "$app: $conditions"; exit 1; }
    sync=$(a get application "$app" --output jsonpath='{.status.sync.status}')
    [[ $sync == Synced || $sync == OutOfSync ]] && break
    [ "$attempt" -lt 60 ] || { echo "$app was not compared: '$sync'"; exit 1; }
    sleep 3
  done
  echo "$app: compared ($sync) at $(a get application "$app" --output jsonpath='{.status.sync.revision}')"
done

echo "--- What each Application would manage"
resources() {
  a get application "$1" --output jsonpath='{range .status.resources[*]}{.kind}/{.name}{"\n"}{end}'
}
expect() {
  local app=$1; shift
  local found
  found=$(resources "$app")
  for want in "$@"; do
    grep --quiet --line-regexp --fixed-strings "$want" <<< "$found" \
      || { echo "$app does not manage $want; it manages:"; echo "$found"; exit 1; }
  done
}
expect root Namespace/invoiceguard SealedSecret/invoiceguard SealedSecret/invoiceguard-postgres \
  Application/invoiceguard-postgres Application/invoiceguard Application/invoiceguard-monitoring
expect invoiceguard-postgres StatefulSet/invoiceguard-postgres Service/invoiceguard-postgres
expect invoiceguard Deployment/invoiceguard-api Deployment/invoiceguard-web Ingress/invoiceguard \
  CronJob/invoiceguard-demo-reset
expect invoiceguard-monitoring Deployment/invoiceguard-monitoring ConfigMap/invoiceguard-monitoring \
  NetworkPolicy/invoiceguard-monitoring
