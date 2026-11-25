from __future__ import annotations

from datetime import datetime

import pytest

from gradescope_cli.api import parsers
from gradescope_cli.exceptions import ParseError
from tests.fixtures import (
    ACCOUNT_PAGE,
    ASSIGNMENT_PAGE,
    ASSIGNMENTS_PAGE,
    ASSIGNMENTS_REACT_PAGE,
    COURSES_PAGE,
    DASHBOARD_PAGE,
    LEADERBOARD_PAGE,
    LEADERBOARD_REACT_PAGE,
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
        assert [c.id for c in courses] == ["111", "222"]  # document order
        assert courses[0].name == "DSC 190 - Capstone Project"  # div.courseBox--name
        assert courses[0].code == "DSC 190"  # h3.courseBox--shortname
        assert courses[0].url == "/courses/111"
        assert courses[0].term == "Spring 2026"  # h2.courseList--term
        assert courses[0].num_assignments == 7  # courseBox--assignments
        assert courses[1].name == "CSE 151A - Intro to ML"  # absolute URL variant
        assert courses[1].term == "Fall 2026"

    def test_term_derived_from_code_when_no_header(self) -> None:
        html = """
        <div><a href="/courses/555">
          <span class="course-card--code">MATH173A_FA26_001</span>
          <span class="course-card--name">DSC 123A</span>
        </a></div>
        """
        courses = parsers.parse_courses(html)
        assert courses[0].term == "Fall 2026"
        assert courses[0].code == "MATH173A_FA26_001"

    def test_sort_courses_by_term(self) -> None:
        courses = parsers.parse_courses(ACCOUNT_PAGE)
        sorted_courses = parsers.sort_courses_by_term(courses)
        assert [c.id for c in sorted_courses] == ["222", "111"]  # Fall 2026 first
        # unknown terms sort last
        from gradescope_cli.api.models import Course as C

        mixed = [C(id="1", name="old"), *sorted_courses]
        assert [c.id for c in parsers.sort_courses_by_term(mixed)] == ["222", "111", "1"]

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
    def test_student_dashboard_table(self) -> None:
        assignments = parsers.parse_assignments(DASHBOARD_PAGE, "111")
        # past rows link to /assignments/<id>/submissions/<sid>; active row uses a button
        assert [a.id for a in assignments] == ["8797872", "8859109", "9113089"]
        hw1 = assignments[0]
        assert hw1.title == "Homework 1"
        assert hw1.url == "/courses/111/assignments/8797872"  # canonical, not the submission url
        assert hw1.due_date == datetime(2026, 10, 13, 5, 0)  # time[dueDate] datetime attr
        assert hw1.status == "graded"
        assert hw1.score == 100.0
        assert hw1.max_score == 100.0
        assert assignments[1].score == 98.0
        assert assignments[1].due_date == datetime(2026, 10, 20, 5, 0)
        hw7 = assignments[2]  # active assignment: button[data-assignment-id]
        assert hw7.title == "Homework 7"
        assert hw7.status == "open"
        assert hw7.due_date == datetime(2026, 12, 3, 17, 0)

    def test_react_assignments_page(self) -> None:
        assignments = parsers.parse_assignments_react(ASSIGNMENTS_REACT_PAGE, "111")
        assert [a.id for a in assignments] == ["777", "888", "999"]
        assert assignments[0].title == "Homework 1"
        assert assignments[0].due_date == datetime(2026, 11, 25, 23, 59)
        assert assignments[1].due_date == datetime(2026, 12, 5, 9, 0)
        assert assignments[2].due_date is None
        assert assignments[0].url == "/courses/111/assignments/777"
        assert assignments[0].status == "submitted"
        assert assignments[0].max_score == 10.0
        assert assignments[1].status == "open"

    def test_react_page_missing(self) -> None:
        assert parsers.parse_assignments_react("<html></html>", "111") == []


class TestParseSubmissionJson:
    def test_graded(self) -> None:
        data = {
            "score": 8.5,
            "max_score": 10.0,
            "submission_questions": [
                {"question_number": 1, "name": "test_basic", "score": 5.0, "max_score": 5.0},
                {"question_number": 2, "name": "test_edge", "score": 3.5, "max_score": 5.0},
            ],
        }
        result = parsers.parse_submission_json(data, "999")
        assert result is not None
        assert result.status == "graded"
        assert result.score == 8.5
        assert result.max_score == 10.0
        assert [(c.name, c.status) for c in result.test_cases] == [
            ("test_basic", "passed"),
            ("test_edge", "failed"),
        ]

    def test_no_score_no_status_returns_none(self) -> None:
        assert parsers.parse_submission_json({}, "999") is None
        assert parsers.parse_submission_json(["not", "a", "dict"], "999") is None

    def test_status_only_is_pending(self) -> None:
        result = parsers.parse_submission_json({"status": "pending"}, "999")
        assert result is not None
        assert result.status == "pending"
        assert result.score is None

    def test_real_react_shape(self) -> None:
        # shape of /submissions/<id>.json?content=react
        data = {
            "assignment": {"total_points": "33.0"},
            "assignment_submission": {"status": "processed", "score": "32.9272"},
            "autograder_results": {
                "score": 32.92716560936051,
                "tests": [
                    {
                        "name": "Check submitted files",
                        "score": 0.0,
                        "max_score": 0.0,
                        "status": "passed",
                    },
                    {"name": "Autograder", "score": 32.9, "max_score": 33.0, "status": "passed"},
                ],
            },
        }
        result = parsers.parse_submission_json(data, "449071192")
        assert result is not None
        assert result.status == "graded"
        assert result.score == 32.9272
        assert result.max_score == 33.0
        assert [(c.name, c.status) for c in result.test_cases] == [
            ("Check submitted files", "passed"),
            ("Autograder", "passed"),
        ]


class TestAssignmentPageProps:
    def test_extracts_viewer_props(self) -> None:
        props = parsers.parse_assignment_page_props(ASSIGNMENT_PAGE)
        assert props is not None
        assert props["assignment_submission"]["id"] == 999
        assert props["paths"]["submission_path"] == "/courses/111/assignments/777/submissions/999"

    def test_missing(self) -> None:
        assert parsers.parse_assignment_page_props("<html></html>") is None

    def test_past_submissions_json(self) -> None:
        data = {
            "past_submissions": [
                {
                    "id": 999,
                    "created_at": "2026-11-24T10:00:00.000000-08:00",
                    "score": "8.5",
                    "status": "processed",
                    "show_path": "/courses/111/assignments/777/submissions/999",
                },
                {"id": 998, "created_at": "2026-11-23T09:00:00-08:00", "score": None},
            ]
        }
        subs = parsers.parse_past_submissions_json(data, "111", "777")
        assert [s.id for s in subs] == ["999", "998"]
        assert subs[0].submitted_at == datetime(2026, 11, 24, 10, 0)
        assert subs[0].score == 8.5
        assert subs[0].status == "processed"
        assert subs[0].url == "/courses/111/assignments/777/submissions/999"
        assert subs[1].score is None
        assert parsers.parse_past_submissions_json({"nope": []}, "111", "777") == []

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


class TestParseSubmissions:
    def test_parses_submission_history(self) -> None:
        subs = parsers.parse_submissions(ASSIGNMENT_PAGE, "111", "777")
        assert [s.id for s in subs] == ["999", "998"]
        assert subs[0].submitted_at == datetime(2026, 11, 24, 10, 0)
        assert subs[0].score == 8.5
        assert subs[0].status == "graded"
        assert subs[1].score is None
        assert subs[1].status == "submitted"
        assert subs[0].url == "/courses/111/assignments/777/submissions/999"
        # the upload form action is not a submission
        assert all(s.id != "" for s in subs)

    def test_empty(self) -> None:
        assert parsers.parse_submissions("<html></html>", "111", "777") == []


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

    def test_react_leaderboard(self) -> None:
        entries = parsers.parse_leaderboard_react(LEADERBOARD_REACT_PAGE)
        assert [(e.rank, e.name) for e in entries] == [(1, "Alice"), (2, "Bob")]
        assert entries[0].score == 99.5  # sum of public task scores
        assert entries[0].submission_id == "1001"
        assert entries[1].score == 80.0
        # per-category scores, in column order, private columns excluded
        assert entries[0].scores == {"task 1": 90.5, "task 2": 9.0}
        assert entries[1].scores == {"task 1": 80.0}
        assert parsers.parse_leaderboard_react("<html></html>") == []
