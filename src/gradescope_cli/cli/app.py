"""argparse-based CLI for gradescope-cli.

Usage:
    gradescope login
    gradescope courses
    gradescope assignments <course_id>
    gradescope submit <course_id> <assignment_id> <files...> [--watch]
    gradescope submissions <course_id> <assignment_id>
    gradescope status <course_id> <assignment_id> <submission_id> [--watch]
    gradescope leaderboard <course_id> <assignment_id>
    gradescope tui
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from gradescope_cli.api.client import GradescopeAPI, GradescopeClient
from gradescope_cli.api.models import AutograderResult, Course, LeaderboardEntry
from gradescope_cli.config import (
    ENV_EMAIL,
    Credentials,
    clear_cached_credentials,
    credentials_path,
    resolve_credentials,
    save_credentials,
)
from gradescope_cli.exceptions import ConfigError, GradescopeError
from gradescope_cli.render import due_text, fmt_number, score_text, status_label

Command = Callable[[argparse.Namespace, GradescopeAPI], int]


def _print_result(result: AutograderResult) -> None:
    score = (
        f"{result.score:g} / {result.max_score:g}"
        if result.score is not None and result.max_score is not None
        else "n/a"
    )
    print(f"status: {result.status}  score: {score}")
    for case in result.test_cases:
        case_score = (
            f"{case.score:g} / {case.max_score:g}"
            if case.score is not None and case.max_score is not None
            else "n/a"
        )
        print(f"  [{case.status:>7}] {case.name}: {case_score}")


def cmd_login(args: argparse.Namespace, client: GradescopeAPI) -> int:
    who = client.email or "Gradescope account"
    print(f"Successfully authenticated with Gradescope as {who}.")
    return 0


def cmd_courses(args: argparse.Namespace, client: GradescopeAPI) -> int:
    courses = client.list_courses()  # sorted by term, most recent first
    if not courses:
        print("No courses found.")
        return 0
    by_term: dict[str, list[Course]] = {}
    for course in courses:
        by_term.setdefault(course.term or "Other", []).append(course)
    width = max(len(c.name) for c in courses)
    for term, term_courses in by_term.items():
        print(f"\n{term} ({len(term_courses)}):")
        for course in term_courses:
            code = f" ({course.code})" if course.code else ""
            print(f"  {course.id:>8}  {course.name:<{width}}{code}")
    return 0


def cmd_assignments(args: argparse.Namespace, client: GradescopeAPI) -> int:
    assignments = client.list_assignments(args.course_id)
    if not assignments:
        print(f"No assignments found for course {args.course_id}.")
        return 0
    width = max(len(a.title) for a in assignments)
    for a in assignments:
        print(
            f"{a.id:>8}  {a.title:<{width}}  due {due_text(a.due_date):<30}  "
            f"{status_label(a.status):<10}  {score_text(a.score, a.max_score)}"
        )
    return 0


def cmd_submit(args: argparse.Namespace, client: GradescopeAPI) -> int:
    submission = client.submit(args.course_id, args.assignment_id, args.files)
    print(f"Submitted {len(args.files)} file(s) to assignment {args.assignment_id}.")
    print(f"submission id: {submission.id}")
    print(f"url: {submission.url}")
    if args.watch:
        result = client.wait_for_autograder(args.course_id, args.assignment_id, submission.id)
        _print_result(result)
    return 0


def cmd_submissions(args: argparse.Namespace, client: GradescopeAPI) -> int:
    submissions = client.list_submissions(args.course_id, args.assignment_id)
    if not submissions:
        print("No submissions yet — submit something first.")
        return 0
    for s in submissions:
        when = due_text(s.submitted_at) if s.submitted_at else "-"
        score = f"{s.score:g}" if s.score is not None else "-"
        print(f"{s.id:>10}  submitted {when:<34}  {status_label(s.status):<10}  score {score}")
    return 0


def cmd_status(args: argparse.Namespace, client: GradescopeAPI) -> int:
    if args.watch:
        result = client.wait_for_autograder(args.course_id, args.assignment_id, args.submission_id)
    else:
        result = client.get_autograder_result(
            args.course_id, args.assignment_id, args.submission_id
        )
    _print_result(result)
    return 0


def cmd_leaderboard(args: argparse.Namespace, client: GradescopeAPI) -> int:
    entries: list[LeaderboardEntry] = client.get_leaderboard(args.course_id, args.assignment_id)
    if not entries:
        print("No leaderboard entries.")
        return 0
    width = max(len(e.name) for e in entries)
    categories: list[str] = []
    for e in entries:
        for col in e.scores:
            if col not in categories:
                categories.append(col)
    header = f"{'rank':>4}  {'name':<{width}}  " + "  ".join(f"{c:>10}" for c in categories)
    if categories:
        header += f"  {'total':>10}"
    print(header)
    for e in entries:
        cells = "  ".join(f"{fmt_number(e.scores.get(c))!s:>10}" for c in categories)
        line = f"{e.rank:>4}  {e.name:<{width}}  {cells}"
        if categories:
            line += f"  {fmt_number(e.score):>10}"
        else:
            line += f"  {fmt_number(e.score)}"
        print(line)
    return 0


def cmd_logout(args: argparse.Namespace, client: GradescopeAPI) -> int:
    """Forget any saved credentials (does not need to sign in)."""
    if clear_cached_credentials():
        print(f"Cleared saved credentials ({credentials_path()}).")
    else:
        print("No saved credentials found.")
    return 0


def _maybe_save_credentials(creds: Credentials) -> None:
    """After an interactive login, offer to cache the credentials (0600 file)."""
    try:
        answer = (
            input(f"Save credentials to {credentials_path()} (file permissions 0600)? [y/N] ")
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        return
    if answer in {"y", "yes"}:
        path = save_credentials(creds)
        print(f"Saved credentials to {path}")


def cmd_tui(args: argparse.Namespace, client: GradescopeAPI) -> int:
    from gradescope_cli.tui import GradescopeApp

    # If the client is not authenticated (no env credentials), the TUI opens
    # with its own login screen. Prefill the email from the env if present.
    GradescopeApp(client, email_hint=os.environ.get(ENV_EMAIL)).run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gradescope",
        description="CLI for Gradescope: browse assignments, submit code, "
        "track the autograder and leaderboards.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "login",
        help="sign in with a regular Gradescope account (prompts if env vars are unset)",
    )
    p.add_argument("--email", help="account email (skips the email prompt)")
    p.set_defaults(func=cmd_login, interactive_login=True)

    p = sub.add_parser("logout", help="forget saved credentials")
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("courses", help="list your courses")
    p.set_defaults(func=cmd_courses)

    p = sub.add_parser("assignments", help="list assignments (and due dates) for a course")
    p.add_argument("course_id")
    p.set_defaults(func=cmd_assignments)

    p = sub.add_parser("submit", help="submit files to an assignment")
    p.add_argument("course_id")
    p.add_argument("assignment_id")
    p.add_argument("files", nargs="+", type=Path, help="file(s) to upload")
    p.add_argument("--watch", action="store_true", help="wait for the autograder to finish")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("submissions", help="list your submissions for an assignment")
    p.add_argument("course_id")
    p.add_argument("assignment_id")
    p.set_defaults(func=cmd_submissions)

    p = sub.add_parser("status", help="show autograder status for a submission")
    p.add_argument("course_id")
    p.add_argument("assignment_id")
    p.add_argument("submission_id")
    p.add_argument("--watch", action="store_true", help="poll until grading finishes")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("leaderboard", help="show the leaderboard for an assignment")
    p.add_argument("course_id")
    p.add_argument("assignment_id")
    p.set_defaults(func=cmd_leaderboard)

    p = sub.add_parser("tui", help="launch the interactive TUI")
    p.set_defaults(func=cmd_tui)

    return parser


def main(argv: Sequence[str] | None = None, *, client: GradescopeAPI | None = None) -> int:
    """Entry point. A pre-authenticated ``client`` may be injected (tests)."""
    args = build_parser().parse_args(argv)
    try:
        if client is None:
            if args.func is cmd_logout:
                client = GradescopeClient()  # logout needs no sign-in
            else:
                # Only `login` prompts on the command line; the TUI has its own
                # login screen, so for `tui` missing credentials are not an error.
                interactive = bool(getattr(args, "interactive_login", False))
                creds: Credentials | None
                try:
                    creds, source = resolve_credentials(
                        interactive=interactive, email=getattr(args, "email", None)
                    )
                except ConfigError:
                    if args.func is not cmd_tui:
                        raise
                    creds, source = None, ""
                real_client = GradescopeClient()
                if creds is not None:
                    real_client.login(creds.email, creds.password)
                    if args.func is cmd_login and source == "prompt":
                        _maybe_save_credentials(creds)
                client = real_client
        result: int = args.func(args, client)
        return result
    except GradescopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
