#!/usr/bin/env bash
# Loads sample-logs.ndjson into Elasticsearch (security disabled, plain HTTP).
set -euo pipefail
ES_URL="${ES_URL:-http://localhost:9200}"
INDEX="${INDEX:-logs-faultline}"
FILE="${1:-sample-logs.ndjson}"

echo "Creating index $INDEX (ignore 'already exists' errors)..."
curl -s -X PUT "$ES_URL/$INDEX" -H 'Content-Type: application/json' --data-binary @mapping.json; echo

echo "Loading $FILE..."
curl -s -X POST "$ES_URL/$INDEX/_bulk?refresh=true" -H 'Content-Type: application/x-ndjson' --data-binary @"$FILE" \
  | python3 -c "import sys,json;r=json.load(sys.stdin);print('errors:',r['errors'],'items:',len(r['items']))"

echo "Document count:"
curl -s "$ES_URL/$INDEX/_count"; echo
