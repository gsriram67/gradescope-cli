from __future__ import annotations

import builtins
import getpass
import json
import os
import stat
from pathlib import Path

import pytest

import gradescope_cli.config as config
from gradescope_cli.config import (
    Credentials,
    clear_cached_credentials,
    load_cached_credentials,
    load_credentials,
    prompt_credentials,
    resolve_credentials,
    save_credentials,
)
from gradescope_cli.exceptions import ConfigError

NO_CACHE = Path("/nonexistent/credentials.json")


def test_loads_from_env() -> None:
    creds = load_credentials(
        {"GRADESCOPE_EMAIL": "student@ucsd.edu", "GRADESCOPE_PASSWORD": "s3cret"},
        cache_path=NO_CACHE,
    )
    assert creds.email == "student@ucsd.edu"
    assert creds.password == "s3cret"


def test_missing_vars_raise_with_names() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_credentials({}, cache_path=NO_CACHE)
    message = str(exc_info.value)
    assert "GRADESCOPE_EMAIL" in message
    assert "GRADESCOPE_PASSWORD" in message


def test_blank_email_counts_as_missing() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_credentials(
            {"GRADESCOPE_EMAIL": "  ", "GRADESCOPE_PASSWORD": "x"}, cache_path=NO_CACHE
        )
    assert "GRADESCOPE_EMAIL" in str(exc_info.value)
    assert "GRADESCOPE_PASSWORD" not in str(exc_info.value)


def test_interactive_prompts_for_missing_values(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["student@ucsd.edu"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "s3cret")
    creds = load_credentials({}, interactive=True, cache_path=NO_CACHE)
    assert creds == Credentials(email="student@ucsd.edu", password="s3cret")


def test_interactive_uses_env_and_email_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "pw-from-env-or-prompt")
    # email given via --email, password from env: nothing should be prompted
    monkeypatch.setattr(
        builtins, "input", lambda prompt="": (_ for _ in ()).throw(AssertionError("prompted!"))
    )
    creds = load_credentials(
        {"GRADESCOPE_PASSWORD": "env-pw"}, interactive=True, email="a@ucsd.edu", cache_path=NO_CACHE
    )
    assert creds.email == "a@ucsd.edu"
    assert creds.password == "env-pw"


def test_prompt_requires_nonempty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda prompt="": "   ")
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
    with pytest.raises(ConfigError, match="required"):
        prompt_credentials({})


class TestCredentialCache:
    def test_save_load_clear_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        creds = Credentials(email="student@ucsd.edu", password="s3cret")
        save_credentials(creds, path)
        assert load_cached_credentials(path) == creds
        assert clear_cached_credentials(path) is True
        assert load_cached_credentials(path) is None
        assert clear_cached_credentials(path) is False

    def test_saved_file_is_user_only(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        save_credentials(Credentials(email="a@b.c", password="x"), path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600

    def test_saved_payload_shape(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        save_credentials(Credentials(email="a@b.c", password="x"), path)
        assert json.loads(path.read_text()) == {"email": "a@b.c", "password": "x"}

    def test_corrupt_or_missing_cache_returns_none(self, tmp_path: Path) -> None:
        assert load_cached_credentials(tmp_path / "nope.json") is None
        bad = tmp_path / "bad.json"
        bad.write_text("not json{")
        assert load_cached_credentials(bad) is None
        empty = tmp_path / "empty.json"
        empty.write_text('{"email": "a@b.c"}')
        assert load_cached_credentials(empty) is None

    def test_resolve_prefers_env_over_cache(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        save_credentials(Credentials(email="cached@x.edu", password="c"), path)
        creds, source = resolve_credentials(
            {"GRADESCOPE_EMAIL": "env@x.edu", "GRADESCOPE_PASSWORD": "e"}, cache_path=path
        )
        assert source == "env"
        assert creds.email == "env@x.edu"

    def test_resolve_uses_cache_when_no_env(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        save_credentials(Credentials(email="cached@x.edu", password="c"), path)
        creds, source = resolve_credentials({}, cache_path=path)
        assert source == "cache"
        assert creds.email == "cached@x.edu"

    def test_resolve_noninteractive_without_any_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="gradescope login"):
            resolve_credentials({}, cache_path=tmp_path / "none.json")

    def test_config_dir_respects_xdg(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert config.config_dir() == tmp_path / "gradescope-cli"
        assert config.credentials_path() == tmp_path / "gradescope-cli" / "credentials.json"
