"""Small .env reader for local API keys."""

from __future__ import annotations

import os
from pathlib import Path


def get_local_env_value(name: str) -> str | None:
    """Return an environment value, falling back to the nearest local .env file."""

    value = os.getenv(name)
    if value is not None and value.strip():
        return value
    return load_local_env().get(name)


def load_local_env(path: str | Path | None = None) -> dict[str, str]:
    """Read key-value pairs from .env without mutating os.environ."""

    env_path = Path(path) if path is not None else _find_local_env()
    if env_path is None or not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if not key:
            continue
        values[key] = _unquote_env_value(value.strip())
    return values


def _find_local_env() -> Path | None:
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
    return None


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
