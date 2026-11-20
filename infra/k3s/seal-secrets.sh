#!/bin/sh
# Seals the two secrets of the demo for the cluster's sealed-secrets controller (ADR-021,
# docs/deploy.md). Run on the server as deploy, where kubectl and kubeseal reach the cluster:
#
#   infra/k3s/seal-secrets.sh /opt/invoiceguard/.env
#
# The restricted roles' passwords, the demo logins and the optional model key come from the .env
# (the server keeps it at /opt/invoiceguard/.env, mode 600, as the source of these values). The
# migration hook sets the restricted roles' passwords on every deploy, so changing one here and
# deploying is enough. The PostgreSQL superuser and owner get random passwords once: PostgreSQL
# takes them only on an empty volume, so an existing sealed-secret-invoiceguard-postgres.yaml is
# kept (changing those needs ALTER ROLE in the database first, then a new sealed file).
# The output files in infra/argocd/apps/ are encrypted for this cluster's key only and are safe to
# commit. No value is printed or passed on a command line.
set -eu

env_file=$1
out=$(cd "$(dirname "$0")/../argocd/apps" && pwd)
ns=invoiceguard

# The last `NAME=value` line of the .env; the file is read, never executed.
value() { sed -n "s/^$1=//p" "$env_file" | tail -n 1; }
need() {
  v=$(value "$1")
  [ -n "$v" ] || { echo "$1 is empty in $env_file" >&2; exit 1; }
  printf '%s' "$v"
}

umask 077
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT


# One assignment per value: `set -e` stops at a failed assignment, not inside a heredoc.
for pair in app-db-password:INVOICEGUARD_APP_DB_PASSWORD \
  mcp-erp-db-password:INVOICEGUARD_MCP_ERP_DB_PASSWORD \
  mcp-registry-db-password:INVOICEGUARD_MCP_REGISTRY_DB_PASSWORD \
  mcp-history-db-password:INVOICEGUARD_MCP_HISTORY_DB_PASSWORD \
  seed-user-email:INVOICEGUARD_SEED_USER_EMAIL seed-user-password:INVOICEGUARD_SEED_USER_PASSWORD; do
  v=$(need "${pair#*:}")
  printf '%s=%s\n' "${pair%%:*}" "$v" >> "$work/app.env"
done
for pair in seed-approver-email:INVOICEGUARD_SEED_APPROVER_EMAIL \
  seed-approver-password:INVOICEGUARD_SEED_APPROVER_PASSWORD llm-api-key:INVOICEGUARD_LLM_API_KEY; do
  v=$(value "${pair#*:}")
  [ -z "$v" ] || printf '%s=%s\n' "${pair%%:*}" "$v" >> "$work/app.env"
done

seal() {
  kubectl create secret generic "$1" --namespace "$ns" --from-env-file "$2" --dry-run=client --output yaml \
    | kubeseal --format yaml > "$out/sealed-secret-$1.yaml"
  echo "wrote $out/sealed-secret-$1.yaml"
}
if [ -e "$out/sealed-secret-invoiceguard-postgres.yaml" ]; then
  echo "kept $out/sealed-secret-invoiceguard-postgres.yaml (the database already uses its passwords)"
else
  superuser=$(openssl rand -hex 24)
  owner=$(openssl rand -hex 24)
  printf 'superuser-password=%s\nowner-password=%s\n' "$superuser" "$owner" > "$work/postgres.env"
  seal invoiceguard-postgres "$work/postgres.env"
fi
seal invoiceguard "$work/app.env"
