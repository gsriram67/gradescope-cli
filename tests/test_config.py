from __future__ import annotations

import builtins
import getpass

import pytest

import gradescope_cli.config as config
from gradescope_cli.config import load_credentials, prompt_credentials
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


def test_interactive_prompts_for_missing_values(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["student@ucsd.edu"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "s3cret")
    creds = load_credentials({}, interactive=True)
    assert creds == config.Credentials(email="student@ucsd.edu", password="s3cret")


def test_interactive_uses_env_and_email_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "pw-from-env-or-prompt")
    # email given via --email, password from env: nothing should be prompted
    monkeypatch.setattr(
        builtins, "input", lambda prompt="": (_ for _ in ()).throw(AssertionError("prompted!"))
    )
    creds = load_credentials(
        {"GRADESCOPE_PASSWORD": "env-pw"}, interactive=True, email="a@ucsd.edu"
    )
    assert creds.email == "a@ucsd.edu"
    assert creds.password == "env-pw"


def test_prompt_requires_nonempty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda prompt="": "   ")
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
    with pytest.raises(ConfigError, match="required"):
        prompt_credentials({})
