#!/usr/bin/env bash
set -euo pipefail

base_url="${ROVER_API_BASE_URL:-http://127.0.0.1:8001}"
if ! command -v curl >/dev/null; then
  printf '%s\n' 'unavailable: curl' >&2
  exit 2
fi

if ! health_response="$(curl --silent --show-error --max-time 3 --write-out $'\n%{http_code}' "$base_url/health" 2>/dev/null)"; then
  printf '%s\n' 'unavailable: API health endpoint did not respond'
  exit 2
fi
health_status="${health_response##*$'\n'}"
health_body="${health_response%$'\n'*}"
if [[ "$health_status" != 2* && "$health_status" != "503" ]]; then
  printf 'failed: API health returned HTTP %s\n' "$health_status" >&2
  exit 1
fi
printf 'API health response (HTTP %s): %s\n' "$health_status" "$health_body"

if ! voice_status="$(curl --silent --show-error --fail --max-time 3 "$base_url/api/v1/voice/status" 2>/dev/null)"; then
  printf '%s\n' 'unavailable: voice status endpoint did not respond'
  exit 2
fi
printf 'voice status response: %s\n' "$voice_status"

legacy_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 3 -X POST "$base_url/api/v1/voice/command")"
if [[ "$legacy_status" != "410" ]]; then
  printf 'failed: legacy voice command returned HTTP %s (expected 410)\n' "$legacy_status" >&2
  exit 1
fi
printf '%s\n' 'legacy voice command correctly disabled (HTTP 410)'
