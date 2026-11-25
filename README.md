# gradescope-cli

A TUI for [Gradescope](https://www.gradescope.com):

- sign in with your Gradescope account (regular email + password, not SSO)
- browse courses (grouped under foldable term sections), assignments and due dates
- submit files (usually code) via a file picker
- track autograder progress and scores (per-test-case results)
- view submission history and assignment leaderboards (per-category columns, searchable)

## Setup

```bash
uv sync          # install dependencies into .venv
uv run gradescope # launch the TUI
```

(`python -m gradescope_cli` works too.)

## Signing in

Use a **regular Gradescope account** (email + password — school/SAML and Google
SSO are not supported). Either export the environment variables:

```bash
export GRADESCOPE_EMAIL="you@ucsd.edu"
export GRADESCOPE_PASSWORD="..."
```

or just launch the TUI with nothing set — it opens a login screen (password
field is masked). Tick **"Remember me"** to cache credentials at
`~/.config/gradescope-cli/credentials.json` with `0600` (user-only)
permissions, so you don't have to re-type them. Env vars always take
precedence over the cache. Forget the saved credentials from the courses
screen with `L`.

## Keys

- login: type email/password, `enter` or click "Log In" · `q` quit
- courses (foldable term tree, current term highlighted): `j/k`/arrows move · `enter`/click a course to open · `enter`/click a term (or its ▸) to fold/unfold · `/` n/a · `r` refresh · `L` forget saved creds · `q` quit
- assignments (due, status chip, score): `j/k` move · `enter`/click open · `s` submit · `l` leaderboard · `/` filter by name · `r` refresh · `h`/`esc` back
- assignment (autograder panel + submissions + test cases): `enter` on a submission tracks its autograder · `s` submit · `g` autograder status · `l` leaderboard · `h`/`esc` back (submitting auto-watches the autograder)
- leaderboard (per-category columns + total): `j/k` move · `/` filter by name · `r` refresh · `h`/`esc` back
- submit modal = **file picker**: `j/k`/arrows move · `enter`/`space`/click toggles a file (✓) · `▸` folds dirs · `Submit` uploads (text input kept for manual paths)

## Development

```bash
uv run pytest          # tests
uv run ruff check      # lint
uv run ruff format     # format
uv run mypy            # type check
```

## Layout

```
src/gradescope_cli/
  api/
    client.py     # GradescopeClient: HTTP + session/CSRF handling (backend)
    parsers.py    # pure HTML/JSON -> model parsing functions
    models.py     # Course, Assignment, Submission, AutograderResult, LeaderboardEntry
  tui/
    app.py        # textual app shell
    screens.py    # login/courses/assignments/assignment/leaderboard screens + modals
    widgets.py    # RowClickTable / NavTree / PickerTree (click-to-open, vim j/k)
  render.py       # text formatting helpers (due dates, score bars, colors)
  app.py          # entry point: resolve credentials, launch the TUI
  config.py       # GRADESCOPE_* env vars + cached credentials file
  exceptions.py
tests/            # pytest suite with a fake HTTP session (no network);
                  # the TUI is tested headless via textual's Pilot
```

The backend talks to Gradescope's web endpoints (session-cookie login with
Rails CSRF `authenticity_token`; HTML pages and embedded React JSON props),
since Gradescope has no public REST API. All network access is injectable, so
the test suite runs fully offline.

## Roadmap

- [x] credential cache in addition to env vars
- [x] autograder per-test-case view + submission history
- [x] file picker in the submit modal
- [ ] two-pane assignment screen (submissions | autograder side by side)
- [ ] OS keyring backend for the credential cache instead of a plaintext 0600 file
