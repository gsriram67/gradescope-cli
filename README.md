# gradescope-cli

A CLI (and soon a TUI) for [Gradescope](https://www.gradescope.com):

- sign in with your Gradescope account parameters (`GRADESCOPE_EMAIL` / `GRADESCOPE_PASSWORD`)
- browse courses, assignments and due dates
- submit files (usually code) to assignments
- track autograder progress and scores
- view assignment leaderboards

## Setup

```bash
uv sync          # install dependencies into .venv
```

Sign in with a **regular Gradescope account** (email + password — school/SAML
and Google SSO are not supported). Either export the environment variables
(e.g. in your shell profile or a `.env` you source):

```bash
export GRADESCOPE_EMAIL="you@ucsd.edu"
export GRADESCOPE_PASSWORD="..."
```

or let `gradescope login` prompt you interactively (password via `getpass`,
never echoed) when the variables are unset:

```bash
uv run gradescope login --email you@ucsd.edu   # only asks for the password
```

## Usage

```bash
uv run gradescope login                                        # sign in / verify credentials
uv run gradescope courses                                      # list courses
uv run gradescope assignments <course_id>                      # list assignments + due dates
uv run gradescope submit <course_id> <assignment_id> file.py... [--watch]
uv run gradescope status <course_id> <assignment_id> <submission_id> [--watch]
uv run gradescope leaderboard <course_id> <assignment_id>
uv run gradescope tui                                          # interactive TUI
```

### TUI

`gradescope tui` opens a login screen first if `GRADESCOPE_EMAIL` /
`GRADESCOPE_PASSWORD` are not set (regular account email + password; SSO is
not supported). Once signed in, the TUI browses courses → assignments →
assignment detail (submit files, watch the autograder, leaderboard).

Keys:

- login: type email/password, `enter` or click "Log In" · `q` quit
- courses (sorted by term, most recent first): `enter` open · `r` refresh · `q` quit
- assignments (due date, status, score bar): `enter` open · `s` submit files · `l` leaderboard · `r` refresh · `esc` back
- assignment (progress bar + per-test-case bars): `s` submit files · `g` autograder status · `l` leaderboard · `esc` back
  (submitting automatically watches the autograder until it finishes)

`python -m gradescope_cli ...` works too.

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
    parsers.py    # pure HTML -> model parsing functions
    models.py     # Course, Assignment, Submission, AutograderResult, LeaderboardEntry
  cli/
    app.py        # argparse CLI (submit / status / leaderboard / tui)
  tui/
    app.py        # textual app shell
    screens.py    # courses/assignments/assignment/leaderboard screens + modals
  config.py       # GRADESCOPE_* environment credentials
  exceptions.py
tests/            # pytest suite with a fake HTTP session (no network);
                  # the TUI is tested headless via textual's Pilot
```

The backend talks to Gradescope's web endpoints (session-cookie login with
Rails CSRF `authenticity_token`, HTML pages parsed with BeautifulSoup), since
Gradescope has no public REST API. All network access is injectable, so the
test suite runs fully offline.

## Roadmap

- [ ] credential file (`~/.config/gradescope-cli`) in addition to env vars
- [ ] richer autograder output (per-test-case view, submission history)
- [ ] file picker (directory tree) in the TUI instead of typed paths
