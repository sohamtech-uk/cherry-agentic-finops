#!/usr/bin/env bash
set -Eeuo pipefail
URL="${1:-https://finops.cherrymoney.co.uk}"
echo "Checking ${URL}"
curl --fail --silent --show-error "${URL}/healthz" | python3 -m json.tool
curl --fail --silent --show-error -X POST "${URL}/api/demo/autonomous" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print({"workflow": d["workflow_id"], "status": d["status"], "action": d["decision"]["action"]})'
