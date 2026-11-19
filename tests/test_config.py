from __future__ import annotations

import pytest

from gradescope_cli.config import load_credentials
from gradescope_cli.exceptions import ConfigError


def test_loads_from_env() -> None:
    creds = load_credentials(
        {"GRADESCOPE_EMAIL": "student@ucsd.edu", "GRADESCOPE_PASSWORD": "s3cret"}
    )
    assert creds.email == "student@ucsd.edu"
    assert creds.password == "s3cret"


def test_missing_vars_raise_with_names() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_credentials({})
    message = str(exc_info.value)
    assert "GRADESCOPE_EMAIL" in message
    assert "GRADESCOPE_PASSWORD" in message


def test_blank_email_counts_as_missing() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_credentials({"GRADESCOPE_EMAIL": "  ", "GRADESCOPE_PASSWORD": "x"})
    assert "GRADESCOPE_EMAIL" in str(exc_info.value)
    assert "GRADESCOPE_PASSWORD" not in str(exc_info.value)
