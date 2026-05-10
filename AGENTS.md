# Agent Notes

This repository follows the same working shape as `pykma` and `pyopinet`.

## Non-negotiables

- Do not commit API keys. Use `KEX_EX_API_KEY` for `data.ex.co.kr` and
  `KEX_GO_API_KEY` for `data.go.kr`.
- Unit tests must not call the network. Use fake sessions or fixtures.
- In documents, write file locations as project-root-relative paths such as
  `kex_openapi/client.py`; do not use local absolute paths.
- Write Python docstrings and explanatory comments in Korean unless quoting
  provider text or preserving code identifiers.
- In this Windows workspace, `rg.exe` can fail with `Access is denied`; when it
  does, search with PowerShell file enumeration and `Select-String` instead.
- Read UTF-8 Markdown with explicit encoding, for example
  `Get-Content -Path README.md -Encoding utf8`, so Korean text does not look
  corrupted in PowerShell output.
- Keep public return values typed Pydantic models or enum values, not raw strings,
  whenever the field has a stable meaning.
- Use `GeoPoint(lon, lat)` for public WGS84 coordinates and expose raw
  ambiguous coordinates separately.
- Preserve code-like identifiers exactly as strings when leading zeroes matter
  (`routeNo`, `unitCode`, branch codes, office codes).
- Handle `list` and single `dict` item shapes. Korean public APIs often switch
  between them when only one item is returned.
- Handle endpoint-named top-level arrays from `data.ex.co.kr`, such as
  `trafficIc`.
- Always inspect body-level API result codes. `data.go.kr` commonly returns
  HTTP 200 for application errors.
- Keep API keys out of repr strings, failure messages, commits, and docs.
- When a sibling library such as `pykma` or `pyopinet` already has a verified
  implementation for the same provider endpoint, port that behavior directly
  into the existing `KexClient` namespace instead of adding a separate wrapper
  layer. This preference can outweigh a narrowly minimal diff when it prevents
  duplicated abstractions and preserves proven parsing rules.

## Module Ownership

- `kex_openapi/_http.py`: transport, retries, API envelope/error mapping.
- `kex_openapi/_convert.py`: small conversion helpers at the response boundary.
- `kex_openapi/codes.py`: enums and code labels.
- `kex_openapi/models.py`: public Pydantic return models.
- `kex_openapi/client.py`: high-level endpoint namespaces and parsing.
- `API_COVERAGE.md`: source-of-truth for implemented vs live-verified API
  status.

## Test Bar

Every new endpoint wrapper should include tests for:

- query parameter names and enum conversion;
- list and single-object response normalization;
- required parameter validation;
- malformed response shape;
- body-level API errors;
- at least one successful typed model conversion.

## Documentation Bar

When behavior changes, update the matching document in the same patch:

- User-facing usage changes: `README.md`.
- Endpoint parameters or response fields: `endpoints.md`.
- Coverage/support status: `API_COVERAGE.md`.
- Code enum changes: `codes.md`.
- Exception or provider error mapping changes: `error-codes.md`.
- Agent workflow or repeated mistakes: `SKILL.md` and this file.
- Documentation style changes: update `CONTRIBUTING.md`, `SKILL.md`, and this
  file together when the rule affects future contributors or agents.

## Commit Hygiene

- Run `python -m compileall kex_openapi tests` and `python -m pytest` before
  pushing.
- Run `python -m mypy kex_openapi` when `mypy` is installed.
- Run `$env:KEX_LIVE="1"; python -m pytest -m live -vv` only when deliberately
  validating against the real `data.ex.co.kr` server.
- Do not include `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`, or
  virtual environments.
- Keep commits focused enough that a failing endpoint can be reverted without
  losing unrelated documentation.
