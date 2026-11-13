#!/usr/bin/env bash
# Upload one invoice to the running API, poll until processing has finished (ADR-007),
# and print the invoice detail (status and check results) as JSON.
# Usage: upload-and-wait.sh FILE COOKIE_JAR [API_URL]
# COOKIE_JAR is a curl cookie file with a logged-in session (curl -c ... /auth/login).
set -euo pipefail

file=$1
cookies=$2
api=${3:-http://localhost:8000}

code=$(curl --silent --show-error --cookie "$cookies" --output /tmp/upload.json --write-out '%{http_code}' -F "file=@$file" "$api/invoices")
if [ "$code" != 202 ]; then
  echo "upload of $file returned HTTP $code" >&2
  cat /tmp/upload.json >&2
  exit 1
fi
id=$(jq -r .id /tmp/upload.json)

for attempt in $(seq 1 60); do
  detail=$(curl --fail --silent --show-error --cookie "$cookies" "$api/invoices/$id")
  status=$(jq -r .status <<<"$detail")
  echo "attempt $attempt: $status" >&2
  case "$status" in
    received|processing) sleep 1 ;;
    *) echo "$detail"; exit 0 ;;
  esac
done
echo "invoice $id still $status after 60 s" >&2
exit 1
