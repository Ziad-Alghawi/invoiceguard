#!/bin/sh
# Downloads the pinned release files of the cluster's platform layer and checks each against its
# SHA-256 (ADR-021, ADR-024): a release URL names whatever its owner (or an attacker) uploads there,
# a hash does not. Used on the server (docs/deploy.md) and by the CI job `helm`.
#
# Usage: infra/k3s/fetch.sh <directory>
set -eu

dir=$1
mkdir -p "$dir"
cd "$dir"

ARGOCD_VERSION=v3.5.7
SEALED_SECRETS_VERSION=0.41.2

curl --fail --silent --show-error --location --output argocd-core-install.yaml \
  "https://raw.githubusercontent.com/argoproj/argo-cd/$ARGOCD_VERSION/manifests/core-install.yaml"
curl --fail --silent --show-error --location --output sealed-secrets-controller.yaml \
  "https://github.com/bitnami-labs/sealed-secrets/releases/download/v$SEALED_SECRETS_VERSION/controller.yaml"
curl --fail --silent --show-error --location --output kubeseal.tar.gz \
  "https://github.com/bitnami-labs/sealed-secrets/releases/download/v$SEALED_SECRETS_VERSION/kubeseal-$SEALED_SECRETS_VERSION-linux-amd64.tar.gz"

# kubeseal's hash is the one in the release's checksums file; the two manifests have none
# published, so these are the hashes of the files as reviewed for R4-4.
sha256sum --check <<'EOF'
a7ab521e55a511af9274294afafc87cddf9621a34ac255b4b20cd31989e1ecbc  argocd-core-install.yaml
5973b18ef77ae91e464bac62542a12c48844a08da69d80e45a8fc7f0d67fe205  sealed-secrets-controller.yaml
666b5db6788ad1dedb56e2d97064e1cc3779aa77bbd6f4b56b62beeb1941ed79  kubeseal.tar.gz
EOF
