#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="jarvis-rover-runtime.service"
UNIT_PATH="/etc/systemd/system/$UNIT_NAME"
MARKER="# Managed-By: jarvis-rover-runtime-installer"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ROOT="$DEFAULT_ROOT"

usage() {
  printf 'Usage: sudo %s [--repo-dir ABSOLUTE_PATH]\n' "${0##*/}"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

while (($# > 0)); do
  case "$1" in
    --repo-dir)
      (($# >= 2)) || fail "--repo-dir requires a path"
      ROOT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -d "$ROOT" ]] || fail "repository directory does not exist: $ROOT"
ROOT="$(cd -- "$ROOT" && pwd)"
[[ "$ROOT" == /* ]] || fail "repository path must be absolute"
[[ "$ROOT" != *[[:space:]]* ]] || fail "repository path cannot contain whitespace"
[[ $EUID -eq 0 ]] || fail "run as root: sudo ${0} --repo-dir $ROOT"

CHECKER="$ROOT/scripts/check_runtime_prerequisites.sh"
TEMPLATE="$ROOT/deploy/jarvis-rover-runtime.service"
[[ -f "$CHECKER" ]] || fail "prerequisite checker is missing: $CHECKER"
[[ -f "$TEMPLATE" ]] || fail "systemd unit template is missing: $TEMPLATE"

# Keep all validation and image preparation ahead of the systemd state change.
bash "$CHECKER"
env -u COMPOSE_PROFILES docker compose \
  --project-directory "$ROOT" --env-file "$ROOT/.env" \
  config --quiet
env -u COMPOSE_PROFILES docker compose \
  --project-directory "$ROOT" --env-file "$ROOT/.env" \
  build rover-runtime

rendered="$(mktemp --tmpdir "${UNIT_NAME}.XXXXXX")"
cleanup() {
  rm -f "$rendered"
}
trap cleanup EXIT

PYTHONPATH="$ROOT/scripts" python3 - "$TEMPLATE" "$ROOT" >"$rendered" <<'PY'
import sys
from pathlib import Path

from runtime_deployment import render_unit

try:
    template = Path(sys.argv[1]).read_text(encoding="utf-8")
    print(render_unit(template, Path(sys.argv[2])), end="")
except Exception as exc:
    print(f"ERROR: cannot render systemd unit: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY

grep -Fqx "$MARKER" "$rendered" || fail "rendered unit is missing the managed marker"

if [[ -e "$UNIT_PATH" ]] && ! grep -Fqx "$MARKER" "$UNIT_PATH"; then
  backup="$UNIT_PATH.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "$UNIT_PATH" "$backup" || fail "could not back up existing unit: $UNIT_PATH"
  printf 'Backed up existing unmanaged unit to %s\n' "$backup"
fi

install -o root -g root -m 0644 "$rendered" "$UNIT_PATH"
systemctl daemon-reload
systemctl enable --now jarvis-rover-runtime.service

for _attempt in {1..60}; do
  if systemctl is-active --quiet "$UNIT_NAME"; then
    printf 'Enabled and started %s\n' "$UNIT_NAME"
    printf 'The runtime starts locked in IDLE; no mapping start/resume command was sent.\n'
    printf 'Next: %s\n' "$ROOT/scripts/real_machine_smoke_test.sh"
    exit 0
  fi
  sleep 1
done

systemctl status "$UNIT_NAME" --no-pager >&2 || true
journalctl -u "$UNIT_NAME" -n 100 --no-pager >&2 || true
fail "$UNIT_NAME did not become active"
