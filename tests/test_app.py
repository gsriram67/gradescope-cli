"""Tests for the TUI-only entry point (gradescope_cli.app.main)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gradescope_cli import app
from gradescope_cli.config import Credentials, save_credentials
from gradescope_cli.tui.app import GradescopeApp


class FakeTty:
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _fake_tty_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", FakeTty())


def test_main_signs_in_from_env_and_launches_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRADESCOPE_EMAIL", "env@ucsd.edu")
    monkeypatch.setenv("GRADESCOPE_PASSWORD", "pw")
    launched: list[GradescopeApp] = []
    monkeypatch.setattr(
        "gradescope_cli.tui.app.GradescopeApp.run", lambda self: launched.append(self)
    )

    class FakeRealClient:
        email: str | None = None

        def __init__(self) -> None:
            self.is_authenticated = False

        def login(self, email: str, password: str) -> None:
            self.email = email
            self.is_authenticated = True

    monkeypatch.setattr(app, "GradescopeClient", FakeRealClient)
    assert app.main() == 0
    assert len(launched) == 1
    client = launched[0].client
    assert client.is_authenticated is True
    assert client.email == "env@ucsd.edu"


def test_main_uses_cache_when_no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GRADESCOPE_EMAIL", raising=False)
    monkeypatch.delenv("GRADESCOPE_PASSWORD", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_credentials(Credentials(email="cached@ucsd.edu", password="pw"))
    launched: list[GradescopeApp] = []
    monkeypatch.setattr(
        "gradescope_cli.tui.app.GradescopeApp.run", lambda self: launched.append(self)
    )

    class FakeRealClient:
        email: str | None = None
        is_authenticated = False

        def login(self, email: str, password: str) -> None:
            self.email = email
            self.is_authenticated = True

    monkeypatch.setattr(app, "GradescopeClient", FakeRealClient)
    assert app.main() == 0
    assert launched[0].client.email == "cached@ucsd.edu"


def test_main_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert app.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "usage: gradescope" in out
    assert "--version" in out


def test_main_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert app.main(["--version"]) == 0
    assert "gradescope-cli" in capsys.readouterr().out


def test_main_without_tty_does_not_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NoTty:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("sys.stdin", NoTty())  # overrides the autouse tty fixture
    launched: list[GradescopeApp] = []
    monkeypatch.setattr(
        "gradescope_cli.tui.app.GradescopeApp.run", lambda self: launched.append(self)
    )
    assert app.main([]) == 0  # prints a note instead of launching the TUI
    assert launched == []
    assert "terminal UI" in capsys.readouterr().err


def test_main_without_creds_opens_tui_login_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GRADESCOPE_EMAIL", raising=False)
    monkeypatch.delenv("GRADESCOPE_PASSWORD", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # empty cache
    launched: list[GradescopeApp] = []
    monkeypatch.setattr(
        "gradescope_cli.tui.app.GradescopeApp.run", lambda self: launched.append(self)
    )
    assert app.main() == 0
    assert launched[0].client.is_authenticated is False  # TUI shows its login screen
