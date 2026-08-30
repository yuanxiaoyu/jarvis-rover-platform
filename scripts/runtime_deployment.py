"""Pure helpers for safe rover runtime deployment tooling.

This module intentionally never evaluates shell syntax or invokes external
commands.  The shell scripts use it to validate the deployment boundary before
changing Docker or systemd state.
"""

from __future__ import annotations

import re
from pathlib import Path


_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PLACEHOLDER = "@REPO_DIR@"


class DeploymentConfigError(ValueError):
    """Raised when deployment configuration is unsafe or incomplete."""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse simple ``KEY=value`` lines without evaluating shell syntax.

    The project environment file is deliberately treated as data.  In
    particular, command substitutions, backticks, and escaped shell commands
    remain literal text and are never passed to a shell.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeploymentConfigError(f"cannot read environment file: {path}") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or _KEY_RE.fullmatch(key) is None:
            raise DeploymentConfigError(
                f"invalid environment assignment on line {line_number}"
            )
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def validate_runtime_env(values: dict[str, str]) -> None:
    """Validate the production runtime's non-optional safety settings."""

    if values.get("ROS_DOMAIN_ID") != "20":
        raise DeploymentConfigError("ROS_DOMAIN_ID must be 20 for the real machine")
    if values.get("ROVER_ROS_BRIDGE_ENABLED", "").lower() != "true":
        raise DeploymentConfigError("ROVER_ROS_BRIDGE_ENABLED must be true")
    if values.get("ROVER_ROS_BRIDGE_REQUIRED", "").lower() != "true":
        raise DeploymentConfigError("ROVER_ROS_BRIDGE_REQUIRED must be true")

    profiles = values.get("COMPOSE_PROFILES", "").strip()
    if profiles:
        raise DeploymentConfigError(
            "Compose profile settings must be empty; hardware and micro-ros-agent "
            "are managed outside the runtime service"
        )


def render_unit(template: str, repo_dir: Path) -> str:
    """Render a systemd template after validating the repository path."""

    if not isinstance(template, str) or _PLACEHOLDER not in template:
        raise DeploymentConfigError("systemd template is missing @REPO_DIR@")
    if not isinstance(repo_dir, Path) or not repo_dir.is_absolute():
        raise DeploymentConfigError("repository path must be absolute")
    path_text = str(repo_dir)
    if any(character.isspace() for character in path_text):
        raise DeploymentConfigError("repository path cannot contain whitespace")
    if "\n" in path_text or "\r" in path_text:
        raise DeploymentConfigError("repository path cannot contain a newline")
    return template.replace(_PLACEHOLDER, path_text)
