#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

for required in \
  "$ROOT/compose.yaml" \
  "$ROOT/.env" \
  "$ROOT/docker/Dockerfile.runtime" \
  "$ROOT/scripts/runtime_deployment.py"; do
  [[ -f "$required" ]] || fail "required file is missing: $required"
done

[[ -x "$(command -v python3 || true)" ]] || fail "python3 is not available"
[[ -x "$(command -v docker || true)" ]] || fail "docker is not available"
[[ -x "$(command -v systemctl || true)" ]] || fail "systemctl is not available"

docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"

PYTHONPATH="$ROOT/scripts" python3 - "$ROOT/.env" <<'PY'
import sys
from pathlib import Path

from runtime_deployment import DeploymentConfigError, parse_env_file, validate_runtime_env

try:
    validate_runtime_env(parse_env_file(Path(sys.argv[1])))
except DeploymentConfigError as exc:
    print(f"ERROR: unsafe runtime environment: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY

compose_args=(
  --project-directory "$ROOT"
  --env-file "$ROOT/.env"
)

# The service unit also clears this variable.  Clearing it here prevents an
# inherited shell setting from enabling either hardware profile accidentally.
config_output="$(env -u COMPOSE_PROFILES docker compose "${compose_args[@]}" config --quiet 2>&1)" || {
  printf '%s\n' "$config_output" >&2
  fail "docker compose config failed"
}

services="$(env -u COMPOSE_PROFILES docker compose "${compose_args[@]}" config --services 2>&1)" || {
  printf '%s\n' "$services" >&2
  fail "could not enumerate default Compose services"
}
if [[ "$services" != "rover-runtime" ]]; then
  printf 'ERROR: default Compose services must be exactly rover-runtime; got:\n%s\n' "$services" >&2
  exit 1
fi

printf 'Runtime prerequisites passed for %s\n' "$ROOT"
printf 'Default Compose service: rover-runtime\n'
printf 'ROS_DOMAIN_ID: 20\n'
printf 'Hardware and micro-ROS-agent profiles remain disabled.\n'
