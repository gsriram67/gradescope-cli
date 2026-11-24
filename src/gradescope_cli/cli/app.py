"""argparse-based CLI for gradescope-cli.

Usage:
    gradescope login
    gradescope courses
    gradescope assignments <course_id>
    gradescope submit <course_id> <assignment_id> <files...> [--watch]
    gradescope status <course_id> <assignment_id> <submission_id> [--watch]
    gradescope leaderboard <course_id> <assignment_id>
    gradescope tui
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from gradescope_cli.api.client import GradescopeAPI, GradescopeClient
from gradescope_cli.api.models import AutograderResult, LeaderboardEntry
from gradescope_cli.config import load_credentials
from gradescope_cli.exceptions import GradescopeError

Command = Callable[[argparse.Namespace, GradescopeAPI], int]


def _fmt_due(due: datetime | None) -> str:
    return due.strftime("%Y-%m-%d %H:%M") if due is not None else "-"


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
    print("Successfully authenticated with Gradescope.")
    return 0


def cmd_courses(args: argparse.Namespace, client: GradescopeAPI) -> int:
    courses = client.list_courses()
    if not courses:
        print("No courses found.")
        return 0
    width = max(len(c.name) for c in courses)
    for course in courses:
        code = f" ({course.code})" if course.code else ""
        print(f"{course.id:>8}  {course.name:<{width}}{code}")
    return 0


def cmd_assignments(args: argparse.Namespace, client: GradescopeAPI) -> int:
    assignments = client.list_assignments(args.course_id)
    if not assignments:
        print(f"No assignments found for course {args.course_id}.")
        return 0
    width = max(len(a.title) for a in assignments)
    for a in assignments:
        print(f"{a.id:>8}  {a.title:<{width}}  due {_fmt_due(a.due_date)}")
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
    for e in entries:
        print(f"{e.rank:>4}  {e.name:<{width}}  {e.score:g}")
    return 0


def cmd_tui(args: argparse.Namespace, client: GradescopeAPI) -> int:
    from gradescope_cli.tui import GradescopeApp

    GradescopeApp(client).run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gradescope",
        description="CLI for Gradescope: browse assignments, submit code, "
        "track the autograder and leaderboards.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="verify that your credentials work")
    p.set_defaults(func=cmd_login)

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
            creds = load_credentials()
            real_client = GradescopeClient()
            real_client.login(creds.email, creds.password)
            client = real_client
        result: int = args.func(args, client)
        return result
    except GradescopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
