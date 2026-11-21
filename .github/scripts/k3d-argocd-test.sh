#!/usr/bin/env bash
# Bootstraps Argo CD core on the k3d cluster as on the server (docs/deploy.md) and checks the
# Applications at this commit (ADR-024). A missing project, a wrong path or revision, or a chart
# Argo CD cannot render shows up as a condition.
#
# The three chart Applications sync for real, over the smoke test's releases, with the images built
# in this job (a pull request's images are not in GHCR), and each must end Synced and Healthy. The
# root app's sync waves wait for that health on the server: an app that stays Progressing (as with
# an Ingress that has no address) holds back every later wave. The root app is only compared: its
# SealedSecrets open only with the server's key, and its sync would point the apps back at `demo`.
#
# Runs after k3d-traefik-config-test.sh, so Traefik has the server's settings.
#
# Usage: .github/scripts/k3d-argocd-test.sh <directory from infra/k3s/fetch.sh> <git revision> <image tag>
set -euo pipefail

platform=$1
revision=$2
tag=$3
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

echo "--- The root app at $revision, without sync: Argo CD reads, renders and compares"
yq ".spec.source.targetRevision = \"$revision\" | del(.spec.syncPolicy)" infra/argocd/root.yaml \
  | kubectl apply --filename -
for attempt in $(seq 1 60); do
  conditions=$(a get application root --output jsonpath='{.status.conditions[*].message}')
  [ -z "$conditions" ] || { echo "root: $conditions"; exit 1; }
  sync=$(a get application root --output jsonpath='{.status.sync.status}')
  [[ $sync == Synced || $sync == OutOfSync ]] && break
  [ "$attempt" -lt 60 ] || { echo "root was not compared: '$sync'"; exit 1; }
  sleep 3
done
echo "root: compared ($sync) at $(a get application root --output jsonpath='{.status.sync.revision}')"

echo "--- The chart apps at $revision, synced with this job's images"
deploy() {
  yq ".spec.source.targetRevision = \"$revision\" $2" "infra/argocd/apps/$1.yaml" \
    | kubectl apply --filename -
}
deploy invoiceguard-postgres
deploy invoiceguard "| (.spec.source.helm.parameters[] | select(.name == \"image.tag\")).value = \"$tag\"
  | .spec.source.helm.parameters += [{\"name\": \"image.pullPolicy\", \"value\": \"Never\"}]"
deploy invoiceguard-monitoring
field() { a get application "$1" --output jsonpath="$2"; }
for app in invoiceguard-postgres invoiceguard invoiceguard-monitoring; do
  for attempt in $(seq 1 120); do
    conditions=$(field "$app" '{.status.conditions[*].message}')
    [ -z "$conditions" ] || { echo "$app: $conditions"; exit 1; }
    sync=$(field "$app" '{.status.sync.status}')
    health=$(field "$app" '{.status.health.status}')
    [[ $sync == Synced && $health == Healthy ]] && break
    [ "$attempt" -lt 120 ] || {
      echo "$app is $sync and $health after 10 minutes; the root app's later waves would wait on it."
      echo "Its operation: $(field "$app" '{.status.operationState.phase}: {.status.operationState.message}')"
      echo "Its resources that are not Healthy:"
      field "$app" '{range .status.resources[*]}{.kind}/{.name}: {.health.status} {.health.message}{"\n"}{end}' \
        | grep --invert-match ': Healthy' || true
      exit 1
    }
    sleep 5
  done
  echo "$app: $sync and $health at $(field "$app" '{.status.sync.revision}')"
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
