"""Loading of GRADESCOPE account parameters from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from gradescope_cli.exceptions import ConfigError

ENV_EMAIL = "GRADESCOPE_EMAIL"
ENV_PASSWORD = "GRADESCOPE_PASSWORD"


@dataclass(frozen=True)
class Credentials:
    """Gradescope account parameters."""

    email: str
    password: str


def load_credentials(env: Mapping[str, str] | None = None) -> Credentials:
    """Read Gradescope credentials from the environment.

    Credentials are taken from the ``GRADESCOPE_EMAIL`` and
    ``GRADESCOPE_PASSWORD`` environment variables. Raises :class:`ConfigError`
    listing every missing variable.
    """
    env = os.environ if env is None else env
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
