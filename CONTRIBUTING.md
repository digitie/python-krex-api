# Contributing

`kex-openapi` is built to stay boring in the best way: small modules, explicit
models, network-free tests, and documentation that captures every sharp edge we
discover.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Before You Change Code

Read the documents that match your task:

- `endpoints.md` for endpoint path, parameters, and response fields.
- `codes.md` for code tables and enum names.
- `error-codes.md` for provider error mapping.
- `SKILL.md` and `AGENTS.md` for implementation rules and repeated mistakes.

## Adding An Endpoint

1. Add or confirm the endpoint entry in `endpoints.md`.
2. Add code enums in `kex_openapi.codes` if the endpoint uses stable public codes.
3. Add a dataclass in `kex_openapi.models` only when the response schema is known.
4. Add the client method in the correct namespace in `kex_openapi.client`.
5. Add tests for query parameters, response parsing, single-object normalization,
   provider errors, malformed shapes, and local validation.
6. Update README examples only for endpoints that users should call directly.

If the path or schema is not verified, return `Page[dict]` and document that
status clearly. We can always make a typed model later; removing a wrong public
model is harder.

## Testing

Required for ordinary changes:

```bash
python -m compileall kex_openapi tests
python -m pytest
python -m mypy kex_openapi
```

For broader changes:

```bash
python -m pytest --cov=kex_openapi --cov-fail-under=90
ruff check .
```

`ruff` may not be installed in every local environment. If it is unavailable,
say that in the PR or commit notes.

## Live API Tests

Default tests must not call real APIs. Live tests should be marked:

```python
@pytest.mark.live
def test_real_endpoint(...):
    ...
```

Live tests must skip cleanly when `KEX_EX_API_KEY` or `KEX_GO_API_KEY` is not
set. Never commit real response files that contain keys, account details, or
other sensitive values.

## Documentation Expectations

Any behavior change should update documentation in the same patch. This keeps
the project useful for humans and for future agent sessions.

Common placements:

- `README.md`: public usage, architecture, validation status.
- `endpoints.md`: endpoint contracts.
- `codes.md`: public code tables.
- `error-codes.md`: exception mapping.
- `SKILL.md` / `AGENTS.md`: workflow rules and repeated mistakes.

## Security

- Do not commit `.env` files.
- Do not paste API keys into tests or examples.
- If a key is accidentally committed, remove it and rotate it.
