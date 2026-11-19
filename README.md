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

Set your credentials (e.g. in your shell profile or a `.env` you source):

```bash
export GRADESCOPE_EMAIL="you@ucsd.edu"
export GRADESCOPE_PASSWORD="..."
```

## Usage

```bash
uv run gradescope login                                        # verify credentials
uv run gradescope courses                                      # list courses
uv run gradescope assignments <course_id>                      # list assignments + due dates
uv run gradescope submit <course_id> <assignment_id> file.py... [--watch]
uv run gradescope status <course_id> <assignment_id> <submission_id> [--watch]
uv run gradescope leaderboard <course_id> <assignment_id>
uv run gradescope tui                                          # interactive TUI (coming soon)
```

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
    app.py        # argparse CLI (submit / status / leaderboard / ...)
    tui.py        # TUI stub (to be built on textual)
  config.py       # GRADESCOPE_* environment credentials
  exceptions.py
tests/            # pytest suite with a fake HTTP session (no network)
```

The backend talks to Gradescope's web endpoints (session-cookie login with
Rails CSRF `authenticity_token`, HTML pages parsed with BeautifulSoup), since
Gradescope has no public REST API. All network access is injectable, so the
test suite runs fully offline.

## Roadmap

- [ ] TUI on `textual` for browsing assignments/due dates and submitting
- [ ] credential file (`~/.config/gradescope-cli`) in addition to env vars
- [ ] richer autograder output (per-test-case view, history of submissions)
- [ ] `watch` mode in the TUI for live autograder progress
