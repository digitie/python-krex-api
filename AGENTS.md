# Agent Notes

This repository follows the same working shape as `pykma` and `pyopinet`.

## Non-negotiables

- Do not commit API keys. Use `KEX_EX_API_KEY` for `data.ex.co.kr` and
  `KEX_GO_API_KEY` for `data.go.kr`.
- Unit tests must not call the network. Use fake sessions or fixtures.
- Keep public return values typed dataclasses or enum values, not raw strings,
  whenever the field has a stable meaning.
- Preserve code-like identifiers exactly as strings when leading zeroes matter
  (`routeNo`, `unitCode`, branch codes, office codes).
- Handle `list` and single `dict` item shapes. Korean public APIs often switch
  between them when only one item is returned.
- Handle endpoint-named top-level arrays from `data.ex.co.kr`, such as
  `trafficIc`.
- Always inspect body-level API result codes. `data.go.kr` commonly returns
  HTTP 200 for application errors.
- Keep API keys out of repr strings, failure messages, commits, and docs.

## Module Ownership

- `kex_openapi._http`: transport, retries, API envelope/error mapping.
- `kex_openapi._convert`: small conversion helpers at the response boundary.
- `kex_openapi.codes`: enums and code labels.
- `kex_openapi.models`: public dataclass return models.
- `kex_openapi.client`: high-level endpoint namespaces and parsing.

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
- Code enum changes: `codes.md`.
- Exception or provider error mapping changes: `error-codes.md`.
- Agent workflow or repeated mistakes: `SKILL.md` and this file.

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
