#!/usr/bin/env bash
# Installs the three Helm charts on the current cluster and smoke-tests them (R4-3, ADR-023;
# monitoring R4-5, ADR-025).
# Used by the CI job `helm` on k3d; runs locally against any k3d cluster too.
#
# Usage: .github/scripts/k3d-smoke-test.sh <image tag> <ingress port>
#   The six images ghcr.io/ziad-alghawi/invoiceguard-*:<image tag> must already be in the cluster
#   (k3d image import); the ingress port is the host port mapped to the cluster's port 80.
set -euo pipefail

tag=$1
ingress="http://localhost:$2"
ns=invoiceguard
api_port=18000
prometheus_port=19090
work=$(mktemp -d)

kubectl create namespace "$ns"
k() { kubectl --namespace "$ns" "$@"; }
secret() { openssl rand -hex 24; }

echo "--- Secrets, created outside the charts (sealed-secrets from R4-4)"
k create secret generic invoiceguard-postgres \
  --from-literal=superuser-password="$(secret)" --from-literal=owner-password="$(secret)"
user_email=reviewer@example.com
user_password=$(secret)
k create secret generic invoiceguard \
  --from-literal=app-db-password="$(secret)" \
  --from-literal=mcp-erp-db-password="$(secret)" \
  --from-literal=mcp-registry-db-password="$(secret)" \
  --from-literal=mcp-history-db-password="$(secret)" \
  --from-literal=seed-user-email="$user_email" \
  --from-literal=seed-user-password="$user_password"

echo "--- PostgreSQL first, then the app: its migration hook needs the database"
helm install invoiceguard-postgres infra/helm/invoiceguard-postgres --namespace "$ns" --wait --timeout 5m
helm install invoiceguard infra/helm/invoiceguard --namespace "$ns" \
  --values infra/helm/ci-values.yaml --set image.tag="$tag" --wait --timeout 10m

echo "--- The owner that ran the migrations is no superuser (ADR-023)"
test "$(k exec statefulset/invoiceguard-postgres -- psql -U postgres -d invoiceguard -tAc \
  "SELECT rolsuper::text || ',' || rolcreaterole::text FROM pg_roles WHERE rolname = 'invoiceguard_owner'")" = false,true

echo "--- The web page through Traefik shows the api ok"
# `helm --wait` returns as soon as the pods are Ready, but the NetworkPolicy controller admits a new
# pod's address a moment later, so web's first call to the api can still be dropped: retry for 30 s.
for attempt in $(seq 1 30); do
  curl --fail --silent --show-error "$ingress/" | grep -qE 'API: (<!-- -->)?erreichbar</p>' && break
  [ "$attempt" -lt 30 ] || { echo "the web page never showed the api ok"; exit 1; }
  sleep 1
done

echo "--- Traefik refuses a body above the limit with 413"
test "$(head -c 12000000 /dev/zero | curl --silent --output /dev/null --write-out '%{http_code}' \
  --data-binary @- "$ingress/upload")" = 413

k port-forward service/invoiceguard-api "$api_port:8000" > /dev/null &
forward=$!
trap 'kill $forward; rm -rf "$work"' EXIT
api="http://localhost:$api_port"
for _ in $(seq 1 30); do curl --silent --output /dev/null "$api/health" && break; sleep 1; done

echo "--- api health and readiness (database reachable as invoiceguard_app)"
curl --fail --silent --show-error "$api/health" | grep '"status":"ok"'
curl --fail --silent --show-error "$api/ready" | grep '"status":"ready"'

echo "--- The demo reset CronJob, run once: samples (KoSIT included) and the login user"
k create job smoke-demo-reset --from=cronjob/invoiceguard-demo-reset
k wait --for=condition=complete job/smoke-demo-reset --timeout=5m

echo "--- Login as the seeded user"
jq -n --arg email "$user_email" --arg password "$user_password" '{email: $email, password: $password}' \
  | curl --fail --silent --show-error --cookie-jar "$work/cookies.txt" \
    -H 'Content-Type: application/json' --data @- "$api/auth/login" > /dev/null
curl --fail --silent --show-error --cookie "$work/cookies.txt" "$api/auth/me" | jq -e --arg email "$user_email" '.email == $email'
curl --fail --silent --show-error --cookie "$work/cookies.txt" "$api/invoices?limit=10" > "$work/demo.json"
jq -r '.[] | .original_filename + " " + .status' "$work/demo.json" | sort | tee "$work/demo.txt"
diff "$work/demo.txt" - <<'TXT'
01_it_service_clean.xml ready
02_it_service_changed_iban.xml blocked
03_logistik_over_po.xml blocked
04_buerobedarf_cii.xml ready
05_unknown_supplier_zugferd.xml ready
06_it_service_injected_note.xml blocked
TXT
clean=$(jq -r '.[] | select(.original_filename == "01_it_service_clean.xml") | .id' "$work/demo.json")
curl --fail --silent --show-error --cookie "$work/cookies.txt" "$api/invoices/$clean" \
  | jq -e '.checks[] | select(.type == "kosit") | .status == "passed"'

echo "--- NetworkPolicy: the api reaches mcp-erp; the web pod and an unlabelled pod do not"
mcp=http://invoiceguard-mcp-erp:8000/mcp
reach='import sys, urllib.request, urllib.error
try:
    urllib.request.urlopen(sys.argv[1], timeout=5)
except urllib.error.HTTPError:
    pass
'
k exec deployment/invoiceguard-api -- python -c "$reach" "$mcp"
if k exec deployment/invoiceguard-web -- node -e \
  "fetch('$mcp', {signal: AbortSignal.timeout(5000)}).then(() => process.exit(0), () => process.exit(1))"; then
  echo "::error::web reached mcp-erp"; exit 1
fi
k run netpol-probe --restart=Never --image="ghcr.io/ziad-alghawi/invoiceguard-api:$tag" \
  --image-pull-policy=Never --command -- python -c "$reach" "$mcp"
k wait --for=jsonpath='{.status.phase}'=Failed pod/netpol-probe --timeout=60s

echo "--- An upgrade runs the migration hook again"
helm upgrade invoiceguard infra/helm/invoiceguard --namespace "$ns" --reuse-values --wait --timeout 10m

echo "--- Prometheus (ADR-025): scrapes every api pod through the headless Service"
helm install invoiceguard-monitoring infra/helm/invoiceguard-monitoring --namespace "$ns" \
  --wait --timeout 5m
k port-forward service/invoiceguard-monitoring "$prometheus_port:9090" > /dev/null &
prometheus_forward=$!
trap 'kill $forward $prometheus_forward; rm -rf "$work"' EXIT
query() {
  curl --fail --silent --show-error --get "http://localhost:$prometheus_port/api/v1/query" \
    --data-urlencode "query=$1" | jq -r '.data.result[0].value[1] // empty'
}
# The first scrape comes within one interval (30 s) of the start.
for attempt in $(seq 1 30); do
  [ "$(query 'up{job="invoiceguard-api"}' 2>/dev/null)" = 1 ] && break
  [ "$attempt" -lt 30 ] || { echo "Prometheus never scraped the api"; exit 1; }
  sleep 3
done
# The logins and invoice reads above, counted by route template.
test "$(query 'sum(invoiceguard_http_requests_total{route="/auth/login",status="200"})')" -ge 1
test "$(query 'invoiceguard_validator_up')" = 1
test "$(query 'count(ALERTS{alertstate="firing"}) or vector(0)')" = 0

echo "--- NetworkPolicy: the web pod cannot reach Prometheus"
if k exec deployment/invoiceguard-web -- node -e \
  "fetch('http://invoiceguard-monitoring:9090/-/ready', {signal: AbortSignal.timeout(5000)}).then(() => process.exit(0), () => process.exit(1))"; then
  echo "::error::web reached Prometheus"; exit 1
fi

echo "--- Memory per pod (requests and limits in values.yaml)"
k top pods || true
