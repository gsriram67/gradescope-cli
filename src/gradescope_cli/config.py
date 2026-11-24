"""Loading of GRADESCOPE account parameters (regular, non-SSO accounts).

Credentials come from the ``GRADESCOPE_EMAIL`` / ``GRADESCOPE_PASSWORD``
environment variables, or — for interactive use — from a prompt
(:func:`prompt_credentials`). School (SAML) and Google SSO sign-in are not
supported; a regular Gradescope email + password is required.
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Mapping
from dataclasses import dataclass

from gradescope_cli.exceptions import ConfigError

ENV_EMAIL = "GRADESCOPE_EMAIL"
ENV_PASSWORD = "GRADESCOPE_PASSWORD"


@dataclass(frozen=True)
class Credentials:
    """Gradescope account parameters (regular account, not SSO)."""

    email: str
    password: str


def credentials_from_env(env: Mapping[str, str]) -> Credentials:
    """Read credentials from a mapping, raising :class:`ConfigError` if missing."""
    email = env.get(ENV_EMAIL, "").strip()
    password = env.get(ENV_PASSWORD, "")
    missing = [name for name, value in ((ENV_EMAIL, email), (ENV_PASSWORD, password)) if not value]
    if missing:
        raise ConfigError(
            "Missing Gradescope credentials: set the "
            + ", ".join(missing)
            + " environment variable(s)."
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


def load_credentials(
    env: Mapping[str, str] | None = None,
    *,
    interactive: bool = False,
    email: str | None = None,
) -> Credentials:
    """Load credentials from the environment, optionally prompting interactively.

    With ``interactive=False`` (the default, for scripting) missing variables
    raise :class:`ConfigError`. With ``interactive=True`` the user is prompted
    for whatever is missing.
    """
    env = os.environ if env is None else env
    try:
        return credentials_from_env(env)
    except ConfigError:
        if not interactive:
            raise
        return prompt_credentials(env, email=email)
