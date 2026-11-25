"""Gradescope account credentials: env vars, cached file, or interactive prompt.

Resolution order (see :func:`resolve_credentials`):

1. ``GRADESCOPE_EMAIL`` / ``GRADESCOPE_PASSWORD`` environment variables
2. a cached credentials file (``~/.config/gradescope-cli/credentials.json``,
   written with ``0600`` permissions by ``gradescope login``)
3. an interactive prompt (password via ``getpass``)

School (SAML) and Google SSO sign-in are not supported; a regular Gradescope
email + password is required.
"""

from __future__ import annotations

import getpass
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from gradescope_cli.exceptions import ConfigError

ENV_EMAIL = "GRADESCOPE_EMAIL"
ENV_PASSWORD = "GRADESCOPE_PASSWORD"

CONFIG_DIR_NAME = "gradescope-cli"
CREDENTIALS_FILE = "credentials.json"


@dataclass(frozen=True)
class Credentials:
    """Gradescope account parameters (regular account, not SSO)."""

    email: str
    password: str


def config_dir() -> Path:
    """``$XDG_CONFIG_HOME/gradescope-cli`` or ``~/.config/gradescope-cli``."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / CONFIG_DIR_NAME


def credentials_path() -> Path:
    return config_dir() / CREDENTIALS_FILE


def save_credentials(creds: Credentials, path: Path | None = None) -> Path:
    """Save credentials to disk with user-only (0600) permissions."""
    path = path or credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"email": creds.email, "password": creds.password}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f)
    os.chmod(path, 0o600)  # tighten if the file already existed
    return path


def load_cached_credentials(path: Path | None = None) -> Credentials | None:
    """Load cached credentials, returning ``None`` if missing/corrupt."""
    path = path or credentials_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        email = str(raw.get("email", "")).strip()
        password = str(raw.get("password", ""))
        if email and password:
            return Credentials(email=email, password=password)
    except (OSError, ValueError, TypeError):
        pass
    return None


def clear_cached_credentials(path: Path | None = None) -> bool:
    """Delete the cached credentials file; True if one existed."""
    path = path or credentials_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def credentials_from_env(env: Mapping[str, str]) -> Credentials:
    """Read credentials from a mapping, raising :class:`ConfigError` if missing."""
    email = env.get(ENV_EMAIL, "").strip()
    password = env.get(ENV_PASSWORD, "")
    missing = [name for name, value in ((ENV_EMAIL, email), (ENV_PASSWORD, password)) if not value]
    if missing:
        raise ConfigError(
            "Missing Gradescope credentials: set the "
            + ", ".join(missing)
            + " environment variable(s), or run `gradescope login` to save them."
        )
    return Credentials(email=email, password=password)


def prompt_credentials(
    env: Mapping[str, str] | None = None, *, email: str | None = None
) -> Credentials:
    """Interactively prompt for a regular Gradescope account email + password.

    Values already present in the environment (or passed via ``email``) are
    used without prompting; the password is read with ``getpass`` so it is
    not echoed.
    """
    env = os.environ if env is None else env
    email_value = (email or env.get(ENV_EMAIL, "")).strip()
    if not email_value:
        email_value = input("Gradescope email: ").strip()
    password = env.get(ENV_PASSWORD, "")
    if not password:
        password = getpass.getpass("Gradescope password: ")
    if not email_value or not password:
        raise ConfigError("a Gradescope email and password are required")
    return Credentials(email=email_value, password=password)


def resolve_credentials(
    env: Mapping[str, str] | None = None,
    *,
    interactive: bool = False,
    email: str | None = None,
    cache_path: Path | None = None,
) -> tuple[Credentials, str]:
    """Resolve credentials: env vars -> cached file -> (optionally) prompt.

    Returns the credentials and their source: ``"env"``, ``"cache"`` or
    ``"prompt"``.
    """
    env = os.environ if env is None else env
    env_error: ConfigError | None = None
    try:
        return credentials_from_env(env), "env"
    except ConfigError as exc:
        env_error = exc
    cached = load_cached_credentials(cache_path)
    if cached is not None:
        return cached, "cache"
    if not interactive:
        assert env_error is not None
        raise ConfigError(f"{env_error} Or run `gradescope login` to save them.") from env_error
    return prompt_credentials(env, email=email), "prompt"


def load_credentials(
    env: Mapping[str, str] | None = None,
    *,
    interactive: bool = False,
    email: str | None = None,
    cache_path: Path | None = None,
) -> Credentials:
    """Load credentials (env -> cache -> prompt when ``interactive``)."""
    return resolve_credentials(env, interactive=interactive, email=email, cache_path=cache_path)[0]
