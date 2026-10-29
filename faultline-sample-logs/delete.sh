#!/usr/bin/env bash
# Deletes the sample index so you can reload fresh logs.
curl -s -X DELETE "${ES_URL:-http://localhost:9200}/${INDEX:-logs-faultline}"; echo
