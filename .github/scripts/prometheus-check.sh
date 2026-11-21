#!/usr/bin/env bash
# Checks the Prometheus config as the invoiceguard-monitoring chart renders it, and runs the alert
# rule unit tests (ADR-025), with promtool from the chart's own pinned image. Needs helm, yq, Docker.
#
# Usage: .github/scripts/prometheus-check.sh
set -euo pipefail

chart=infra/helm/invoiceguard-monitoring
image=$(yq '.image.repository + ":" + .image.tag' "$chart/values.yaml")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# promtool runs as nobody in the container; mktemp's directory is the runner user's only.
chmod 755 "$work"

echo "--- The rendered prometheus.yml and rules.yml are valid"
helm template invoiceguard-monitoring "$chart" --namespace invoiceguard \
  --show-only templates/configmap.yaml > "$work/configmap.yaml"
yq '.data["prometheus.yml"]' "$work/configmap.yaml" > "$work/prometheus.yml"
yq '.data["rules.yml"]' "$work/configmap.yaml" > "$work/rules.yml"
# The config names the rules at /etc/prometheus/rules.yml, where the pod mounts the ConfigMap.
docker run --rm --volume "$work:/etc/prometheus:ro" --entrypoint promtool "$image" \
  check config /etc/prometheus/prometheus.yml

echo "--- Each alert fires in its unit test (and stays quiet where it should)"
docker run --rm --volume "$PWD/$chart:/chart:ro" --entrypoint promtool "$image" \
  test rules /chart/tests/rules.test.yml
