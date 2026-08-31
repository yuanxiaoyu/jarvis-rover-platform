#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--play-test-tone" ]]; then echo "explicit playback tone requested"; else echo "capture/model smoke check only"; fi
command -v arecord >/dev/null || { echo "arecord unavailable"; exit 1; }
