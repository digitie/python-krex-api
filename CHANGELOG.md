# Changelog

All notable changes to this project are recorded here.

## 0.1.0 - 2026-04-30

Initial package scaffold and first implementation pass.

### Added

- `KexClient` with `traffic`, `tollfee`, `restarea`, `facility`, `admin`, and
  `reference` namespaces.
- `data.ex.co.kr` and `data.go.kr` HTTP helpers with retry handling and
  provider error-code mapping.
- Public dataclasses for key response types:
  `TrafficByIc`, `TrafficFlow`, `Incident`, `TollFee`, `Tollgate`,
  `RestArea`, `FoodPrice`, `Route`, and `Page`.
- Stable enum code tables for car type, TCS type, road operator, direction,
  traffic time unit, congestion level, and discount type.
- Conversion helpers for API string values: dates, numbers, Y/N flags, and
  single-item response normalization.
- Network-free pytest suite covering query construction, parsing, local
  validation, body-level provider errors, retry behavior, and malformed
  responses.
- Documentation set:
  `README.md`, `endpoints.md`, `codes.md`, `error-codes.md`, `SKILL.md`,
  `AGENTS.md`, `CONTRIBUTING.md`, and `CHANGELOG.md`.
- Existing remote `LICENSE` preserved and package metadata aligned to
  GPL-3.0-or-later.

### Validation

- `python -m compileall kex_openapi tests`
- `python -m pytest`
- `python -m pytest --cov=kex_openapi --cov-fail-under=90`
- `python -m mypy kex_openapi`

`ruff` was not available in the initial local environment.
