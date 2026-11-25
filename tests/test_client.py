from __future__ import annotations

from pathlib import Path

import pytest

from gradescope_cli.api.client import GradescopeClient
from gradescope_cli.exceptions import (
    APIError,
    AuthError,
    AutograderTimeoutError,
    NotFoundError,
)
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
    LOGIN_PAGE_FAILED,
    SUBMISSION_PAGE_GRADED,
    SUBMISSION_PAGE_PENDING,
    FakeResponse,
    FakeSession,
)


def wire_login(session: FakeSession, success: bool = True) -> None:
    session.add("GET", "/login", FakeResponse(text=LOGIN_PAGE))

    def post_login(**kwargs: object) -> FakeResponse:
        if success:
            session.cookies["_gradescope_session"] = "cookie-value"
            return FakeResponse(status_code=302, headers={"Location": "/courses"})
        return FakeResponse(status_code=200, text=LOGIN_PAGE_FAILED)

    session.add("POST", "/login", post_login)


class TestLogin:
    def test_success(self, session: FakeSession, client: GradescopeClient) -> None:
        wire_login(session, success=True)
        client.login("student@ucsd.edu", "hunter2")
        assert client.is_authenticated
        post = session.last_request("POST")
        data = post["data"]
        assert data["session[email]"] == "student@ucsd.edu"
        assert data["session[password]"] == "hunter2"
        assert data["authenticity_token"] == "tok-login-123"
        assert data["commit"] == "Log In"  # same fields as the web login form
        assert post["allow_redirects"] is False
        assert client.email == "student@ucsd.edu"

    def test_failure_raises_auth_error(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        wire_login(session, success=False)
        with pytest.raises(AuthError, match="SSO"):
            client.login("student@ucsd.edu", "wrong")
        assert not client.is_authenticated
        assert client.email is None

    def test_ensure_logged_in_only_once(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        wire_login(session, success=True)
        client.ensure_logged_in("a", "b")
        client.ensure_logged_in("a", "b")
        assert len([r for r in session.requests if r["url"].endswith("/login")]) == 2  # GET + POST


class TestBrowse:
    def test_list_courses_from_account_page_sorted_by_term(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        session.add("GET", "/account", FakeResponse(text=ACCOUNT_PAGE))
        session.add("GET", "/courses", FakeResponse(text="<html></html>"))
        courses = client.list_courses()
        # Fall 2026 (222) sorts before Spring 2026 (111)
        assert [c.id for c in courses] == ["222", "111"]
        assert courses[0].name == "CSE 151A - Intro to ML"
        assert courses[0].term == "Fall 2026"

    def test_list_courses_fallback_to_courses_page(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        session.add("GET", "/account", FakeResponse(text="<html></html>"))
        session.add("GET", "/courses", FakeResponse(text=COURSES_PAGE))
        courses = client.list_courses()
        assert [c.id for c in courses] == ["111", "222"]

    def test_list_assignments_from_dashboard(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        session.add("GET", "/courses/111", FakeResponse(text=DASHBOARD_PAGE))
        session.add("GET", "/courses/111/assignments", FakeResponse(text="<html></html>"))
        assignments = client.list_assignments("111")
        # sorted by time-to-due: upcoming first, past at the bottom (most overdue last)
        assert [a.id for a in assignments] == ["9113089", "8859109", "8797872"]
        assert assignments[0].status == "open"  # Homework 7, due 2026-12-03
        assert assignments[0].due_date is not None
        assert assignments[0].due_date.year == 2026
        assert assignments[2].status == "graded"  # Homework 1, most overdue -> bottom
        assert assignments[2].score == 100.0

    def test_list_assignments_fallback_page(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        session.add("GET", "/courses/111", FakeResponse(text="<html></html>"))
        session.add("GET", "/courses/111/assignments", FakeResponse(text=ASSIGNMENTS_PAGE))
        assignments = client.list_assignments("111")
        assert [a.id for a in assignments] == ["777", "888", "999"]

    def test_assignments_dashboard_404_falls_back_to_react_page(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        # /courses/111 404s; the /assignments page embeds the React table
        session.add("GET", "/courses/111/assignments", FakeResponse(text=ASSIGNMENTS_REACT_PAGE))
        assignments = client.list_assignments("111")
        assert [a.id for a in assignments] == ["777", "888", "999"]
        assert assignments[0].due_date is not None

    def test_assignments_empty_dashboard_and_401_fallback_returns_empty(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        # dashboard loads but has no table; /assignments is instructor-only (401)
        session.add("GET", "/courses/111", FakeResponse(text="<html></html>"))
        session.add("GET", "/courses/111/assignments", FakeResponse(status_code=401))
        assert client.list_assignments("111") == []

    def test_assignments_all_pages_404_raises_not_found(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        with pytest.raises(NotFoundError):
            client.list_assignments("111")

    def test_redirect_to_login_raises_auth_error(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        # session expired: /account bounces to /login (requests follows it)
        session.add(
            "GET",
            "/account",
            FakeResponse(text=LOGIN_PAGE, url="https://gradescope.test/login"),
        )
        with pytest.raises(AuthError, match="not authenticated"):
            client.list_courses()

    def test_404_raises_not_found(self, client: GradescopeClient) -> None:
        with pytest.raises(NotFoundError):
            client.list_courses()


class TestSubmit:
    def test_submit_uploads_files_and_parses_redirect(
        self, session: FakeSession, client: GradescopeClient, tmp_path: Path
    ) -> None:
        code = tmp_path / "solution.py"
        code.write_text("print('hi')\n")
        notes = tmp_path / "notes.txt"
        notes.write_text("hello\n")
        session.add("GET", "/courses/111/assignments/777", FakeResponse(text=ASSIGNMENT_PAGE))
        session.add(
            "POST",
            "/courses/111/assignments/777/submissions",
            FakeResponse(
                status_code=302,
                headers={"Location": "/courses/111/assignments/777/submissions/999"},
            ),
        )
        submission = client.submit("111", "777", [code, str(notes)])
        assert submission.id == "999"
        assert submission.url == "/courses/111/assignments/777/submissions/999"
        post = session.last_request("POST")
        # CSRF token goes in the X-CSRF-Token header (from the csrf-token meta tag)
        assert post["headers"]["X-CSRF-Token"] == "tok-meta-789"
        files = post["files"]
        assert [name for _, (name, _) in files] == ["solution.py", "notes.txt"]

    def test_submit_without_redirect_raises(
        self, session: FakeSession, client: GradescopeClient, tmp_path: Path
    ) -> None:
        f = tmp_path / "a.py"
        f.write_text("x = 1\n")
        session.add("GET", "/courses/111/assignments/777", FakeResponse(text=ASSIGNMENT_PAGE))
        session.add(
            "POST",
            "/courses/111/assignments/777/submissions",
            FakeResponse(status_code=422, text="unprocessable"),
        )
        with pytest.raises(APIError) as exc_info:
            client.submit("111", "777", [f])
        assert exc_info.value.status_code == 422

    def test_submit_requires_files(self, client: GradescopeClient) -> None:
        with pytest.raises(ValueError, match="at least one file"):
            client.submit("111", "777", [])


class TestSubmissions:
    def test_list_submissions_via_past_submissions_json(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        session.add("GET", "/courses/111/assignments/777", FakeResponse(text=ASSIGNMENT_PAGE))
        session.add(
            "GET",
            "/courses/111/assignments/777/submissions/999.json",
            FakeResponse(
                json_data={
                    "past_submissions": [
                        {
                            "id": 999,
                            "created_at": "2026-11-24T10:00:00.000000-08:00",
                            "score": "8.5",
                            "status": "processed",
                        },
                        {"id": 998, "created_at": "2026-11-23T09:00:00-08:00", "score": None},
                    ]
                }
            ),
        )
        subs = client.list_submissions("111", "777")
        assert [s.id for s in subs] == ["999", "998"]
        assert subs[0].score == 8.5
        assert subs[0].submitted_at is not None
        assert subs[0].status == "processed"

    def test_list_submissions_html_fallback(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        # .json endpoint missing (404) -> parse submission links from the HTML page
        session.add("GET", "/courses/111/assignments/777", FakeResponse(text=ASSIGNMENT_PAGE))
        subs = client.list_submissions("111", "777")
        assert [s.id for s in subs] == ["999", "998"]
        assert subs[0].score == 8.5


class TestAutograder:
    SUBMISSION_PATH = "/courses/111/assignments/777/submissions/999"

    def test_get_result_graded(self, session: FakeSession, client: GradescopeClient) -> None:
        session.add("GET", self.SUBMISSION_PATH, FakeResponse(text=SUBMISSION_PAGE_GRADED))
        result = client.get_autograder_result("111", "777", "999")
        assert result.status == "graded"
        assert result.score == 8.5
        assert result.max_score == 10.0
        assert [c.name for c in result.test_cases] == ["test_basic", "test_edge_case"]

    def test_get_result_prefers_json_endpoint(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        session.add(
            "GET",
            self.SUBMISSION_PATH + ".json",
            FakeResponse(
                json_data={
                    "score": 9.0,
                    "max_score": 10.0,
                    "submission_questions": [
                        {"question_number": 1, "name": "q1", "score": 9.0, "max_score": 10.0}
                    ],
                }
            ),
        )
        session.add("GET", self.SUBMISSION_PATH, FakeResponse(text=SUBMISSION_PAGE_GRADED))
        result = client.get_autograder_result("111", "777", "999")
        assert result.status == "graded"
        assert result.score == 9.0  # from JSON, not the HTML page (8.5)
        assert [c.name for c in result.test_cases] == ["q1"]

    def test_get_result_json_unavailable_falls_back_to_html(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        # .json 404s (FakeSession default) -> HTML page is used
        session.add("GET", self.SUBMISSION_PATH, FakeResponse(text=SUBMISSION_PAGE_GRADED))
        result = client.get_autograder_result("111", "777", "999")
        assert result.score == 8.5

    def test_wait_until_graded(self, session: FakeSession, client: GradescopeClient) -> None:
        calls = {"n": 0}

        def handler(**kwargs: object) -> FakeResponse:
            calls["n"] += 1
            text = SUBMISSION_PAGE_PENDING if calls["n"] < 3 else SUBMISSION_PAGE_GRADED
            return FakeResponse(text=text)

        session.add("GET", self.SUBMISSION_PATH, handler)
        result = client.wait_for_autograder(
            "111", "777", "999", poll_interval=0, timeout=60, sleep=lambda _: None
        )
        assert result.status == "graded"
        assert calls["n"] == 3

    def test_wait_timeout(self, session: FakeSession, client: GradescopeClient) -> None:
        session.add("GET", self.SUBMISSION_PATH, FakeResponse(text=SUBMISSION_PAGE_PENDING))
        with pytest.raises(AutograderTimeoutError):
            client.wait_for_autograder(
                "111", "777", "999", poll_interval=0, timeout=0, sleep=lambda _: None
            )


class TestLeaderboard:
    def test_get_leaderboard(self, session: FakeSession, client: GradescopeClient) -> None:
        session.add(
            "GET",
            "/courses/111/assignments/777/leaderboard",
            FakeResponse(text=LEADERBOARD_PAGE),
        )
        entries = client.get_leaderboard("111", "777")
        assert [(e.rank, e.name, e.score) for e in entries] == [
            (1, "Alice", 99.5),
            (2, "Bob", 87.0),
        ]

    def test_get_leaderboard_react_page(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        session.add(
            "GET",
            "/courses/111/assignments/777/leaderboard",
            FakeResponse(text=LEADERBOARD_REACT_PAGE),
        )
        entries = client.get_leaderboard("111", "777")
        assert [(e.rank, e.name, e.score) for e in entries] == [
            (1, "Alice", 99.5),
            (2, "Bob", 80.0),
        ]
        assert entries[0].submission_id == "1001"

    def test_leaderboard_404_friendly_error(
        self, session: FakeSession, client: GradescopeClient
    ) -> None:
        with pytest.raises(NotFoundError, match="not enabled"):
            client.get_leaderboard("111", "777")
