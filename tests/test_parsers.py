from __future__ import annotations

from datetime import datetime

import pytest

from gradescope_cli.api import parsers
from gradescope_cli.exceptions import ParseError
from tests.fixtures import (
    ACCOUNT_PAGE,
    ASSIGNMENT_PAGE,
    ASSIGNMENTS_PAGE,
    COURSES_PAGE,
    DASHBOARD_PAGE,
    LEADERBOARD_PAGE,
    LOGIN_PAGE,
    SUBMISSION_PAGE_GRADED,
    SUBMISSION_PAGE_PENDING,
)


class TestExtractCsrfToken:
    def test_reads_token(self) -> None:
        assert parsers.extract_csrf_token(LOGIN_PAGE) == "tok-login-123"
        assert parsers.extract_csrf_token(ASSIGNMENT_PAGE) == "tok-submit-456"

    def test_missing_token_raises(self) -> None:
        with pytest.raises(ParseError):
            parsers.extract_csrf_token("<html><body>no form</body></html>")


class TestParseDueDate:
    NOW = datetime(2026, 11, 18, 12, 0)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Nov 25, 2026 at 11:59pm", datetime(2026, 11, 25, 23, 59)),
            ("Nov 25, 2026 at 11:59pm PDT", datetime(2026, 11, 25, 23, 59)),
            ("2026-11-25 23:59:00 -0800", datetime(2026, 11, 25, 23, 59)),  # tz stripped
            ("2026-12-01 23:59", datetime(2026, 12, 1, 23, 59)),
        ],
    )
    def test_formats(self, text: str, expected: datetime) -> None:
        assert parsers.parse_due_date(text, now=self.NOW) == expected

    def test_yearless_uses_current_year(self) -> None:
        assert parsers.parse_due_date("Dec 5 at 9:00am", now=self.NOW) == datetime(
            2026, 12, 5, 9, 0
        )

    def test_yearless_past_date_rolls_to_next_year(self) -> None:
        assert parsers.parse_due_date("Jan 2 at 9:00am", now=self.NOW) == datetime(2027, 1, 2, 9, 0)

    def test_unparseable_returns_none(self) -> None:
        assert parsers.parse_due_date("no due date") is None
        assert parsers.parse_due_date("") is None


class TestParseCourses:
    def test_account_page_course_boxes(self) -> None:
        courses = parsers.parse_courses(ACCOUNT_PAGE)
        assert [c.id for c in courses] == ["111", "222"]
        assert courses[0].name == "DSC 190 - Capstone Project"  # div.courseBox--name
        assert courses[0].code == "DSC 190"  # h3.courseBox--shortname
        assert courses[0].url == "/courses/111"
        assert courses[1].name == "CSE 151A - Intro to ML"  # absolute URL variant

    def test_parses_and_dedupes(self) -> None:
        courses = parsers.parse_courses(COURSES_PAGE)
        assert [c.id for c in courses] == ["111", "222"]
        assert courses[0].name == "DSC 190 - Capstone Project"
        assert courses[0].code == "DSC 190"
        assert courses[0].url == "/courses/111"
        # absolute URL variant
        assert courses[1].name == "CSE 151A"

    def test_empty(self) -> None:
        assert parsers.parse_courses("<html></html>") == []


class TestParseAssignments:
    def test_dashboard_rows(self) -> None:
        assignments = parsers.parse_assignments(DASHBOARD_PAGE, "111")
        assert [a.id for a in assignments] == ["777", "888", "999"]
        assert assignments[0].title == "Homework 1"
        # the due date is the *latest* date in the row (close, not open), tz stripped
        assert assignments[0].due_date == datetime(2026, 11, 25, 23, 59)
        assert assignments[1].due_date is not None and assignments[1].due_date.hour == 9
        assert assignments[2].due_date is None

    def test_parses_titles_and_due_dates(self) -> None:
        assignments = parsers.parse_assignments(ASSIGNMENTS_PAGE, "111")
        assert [a.id for a in assignments] == ["777", "888", "999"]
        assert assignments[0].title == "Homework 1"
        assert assignments[0].due_date == datetime(2026, 11, 25, 23, 59)
        assert assignments[1].due_date is not None
        assert assignments[1].due_date.hour == 9
        assert assignments[2].due_date is None
        assert assignments[0].url == "/courses/111/assignments/777"
        assert all(a.course_id == "111" for a in assignments)

    def test_ignores_other_courses(self) -> None:
        html = '<a href="/courses/999/assignments/1">Other</a>'
        assert parsers.parse_assignments(html, "111") == []


class TestParseSubmissionId:
    def test_from_redirect(self) -> None:
        assert parsers.parse_submission_id("/courses/111/assignments/777/submissions/999") == "999"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ParseError):
            parsers.parse_submission_id("/courses")


class TestParseSubmissionStatus:
    def test_pending(self) -> None:
        status = parsers.parse_submission_status(SUBMISSION_PAGE_PENDING)
        assert status.status == "pending"
        assert status.score is None
        assert status.test_cases == ()

    def test_graded(self) -> None:
        status = parsers.parse_submission_status(SUBMISSION_PAGE_GRADED)
        assert status.status == "graded"
        assert status.score == 8.5
        assert status.max_score == 10.0
        assert len(status.test_cases) == 2
        basic, edge = status.test_cases
        assert basic.name == "test_basic"
        assert basic.status == "passed"
        assert basic.score == 5.0
        assert edge.status == "failed"
        assert edge.score == 3.5
        assert edge.max_score == 5.0


class TestParseLeaderboard:
    def test_parses_rows(self) -> None:
        entries = parsers.parse_leaderboard(LEADERBOARD_PAGE)
        assert len(entries) == 2
        assert entries[0].rank == 1
        assert entries[0].name == "Alice"
        assert entries[0].score == 99.5
        assert entries[0].submission_id == "1001"
        assert entries[1].name == "Bob"
        assert entries[1].submission_id is None

    def test_missing_table_raises(self) -> None:
        with pytest.raises(ParseError):
            parsers.parse_leaderboard("<html></html>")
