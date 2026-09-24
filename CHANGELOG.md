# Changelog

## [0.1.0.0] - 2026-09-24

### Added

- Operate the rover from a live web console with API-backed telemetry, maps, camera, gimbal, and voice status.
- Explore mapped frontiers with Nav2 path planning, configurable zones, and a fail-closed safety gate.
- Use a local wake-word voice assistant with speech recognition, text-to-speech, and confirmation for mapping actions.
- Install the rover runtime and voice service with systemd units and deployment scripts.

### Changed

- Update sensor timestamp handling, EKF configuration, SLAM bringup, and mapping runtime integration.
- Replace demo dashboard data and older runtime instructions with the live integration and acceptance guidance.

### Removed

- Remove superseded mapping interfaces, runtime launch helpers, and deployment scripts.
