"""Resolve ${ENV} and Docker secret files without logging values."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_ENV_TOKEN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")
_ENV_ONLY = re.compile(r"^\$\{([A-Z0-9_]+)(?::-([^}]*))?\}$")
_FILE_PATTERN = re.compile(r"^file:(.+)$")


def _lookup_env(name: str, default: str | None) -> str:
    docker_secret = Path("/run/secrets") / name.lower()
    if docker_secret.is_file():
        return docker_secret.read_text(encoding="utf-8").strip()
    if name in os.environ:
        return os.environ[name]
    if default is not None:
        return default
    raise ValueError(f"Missing secret/environment variable: {name}")


def resolve_secret(value: Any, *, secrets_dir: str | None = None) -> Any:
    if not isinstance(value, str):
        return value
    file_match = _FILE_PATTERN.match(value.strip())
    if file_match:
        path = Path(file_match.group(1))
        if secrets_dir and not path.is_absolute():
            path = Path(secrets_dir) / path
        return path.read_text(encoding="utf-8").strip()
    # Whole-string ${ENV} (preserves missing-without-default as error)
    env_only = _ENV_ONLY.match(value.strip())
    if env_only:
        return _lookup_env(env_only.group(1), env_only.group(2))
    # Inline / concatenated ${A}${B} patterns (e.g. base URL + path)
    if "${" in value:

        def repl(match: re.Match[str]) -> str:
            return _lookup_env(match.group(1), match.group(2))

        return _ENV_TOKEN.sub(repl, value)
    return value


def resolve_tree(data: Any, *, secrets_dir: str | None = None) -> Any:
    if isinstance(data, dict):
        return {k: resolve_tree(v, secrets_dir=secrets_dir) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_tree(v, secrets_dir=secrets_dir) for v in data]
    return resolve_secret(data, secrets_dir=secrets_dir)
