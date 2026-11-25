"""HTTP client for the (unofficial) Gradescope web API.

Gradescope does not publish a public REST API, so this client drives the
same HTML endpoints the web app uses: session-cookie login with a CSRF
``authenticity_token``, and page scraping for courses, assignments,
submissions, autograder results and leaderboards.

The HTTP layer is injected as a small :class:`HTTPSession` protocol so the
client can be unit-tested with a fake session (see ``tests/fixtures.py``).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from gradescope_cli.api import parsers
from gradescope_cli.api.models import (
    Assignment,
    AutograderResult,
    Course,
    LeaderboardEntry,
    Submission,
)
from gradescope_cli.exceptions import (
    APIError,
    AuthError,
    AutograderTimeoutError,
    NotFoundError,
)

BASE_URL = "https://www.gradescope.com"

SESSION_COOKIE = "_gradescope_session"


class HTTPResponse(Protocol):
    """Minimal response interface (satisfied by ``requests.Response``)."""

    status_code: int
    text: str
    url: str
    # requests uses CaseInsensitiveDict, fakes use dict; Any keeps the
    # protocol compatible with both (protocol attributes match invariantly).
    headers: Any

    def json(self) -> Any: ...


class HTTPSession(Protocol):
    """Minimal session interface (satisfied by ``requests.Session``)."""

    cookies: Any  # requests.CookieJar / dict in fakes; we only use `in`.

    def get(self, url: str, **kwargs: Any) -> HTTPResponse: ...

    def post(self, url: str, **kwargs: Any) -> HTTPResponse: ...


class GradescopeAPI(Protocol):
    """Backend interface consumed by the CLI/TUI (easy to fake in tests)."""

    email: str | None  # the account email after a successful login

    @property
    def is_authenticated(self) -> bool: ...

    def login(self, email: str, password: str) -> None: ...

    def list_courses(self) -> list[Course]: ...

    def list_assignments(self, course_id: str) -> list[Assignment]: ...

    def submit(
        self, course_id: str, assignment_id: str, files: Sequence[str | Path]
    ) -> Submission: ...

    def list_submissions(self, course_id: str, assignment_id: str) -> list[Submission]: ...

    def get_autograder_result(
        self, course_id: str, assignment_id: str, submission_id: str
    ) -> AutograderResult: ...

    def wait_for_autograder(
        self,
        course_id: str,
        assignment_id: str,
        submission_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> AutograderResult: ...

    def get_leaderboard(self, course_id: str, assignment_id: str) -> list[LeaderboardEntry]: ...


class GradescopeClient:
    """Client for the Gradescope web API."""

    def __init__(
        self,
        session: HTTPSession | None = None,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        if session is not None:
            self._session = session
        else:
            # requests.Session has keyword-only params (no **kwargs), so it
            # cannot structurally satisfy HTTPSession; the calls we make are
            # covered by the protocol, hence the cast.
            self._session = cast(HTTPSession, requests.Session())
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._logged_in = False
        self.email: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self._logged_in or SESSION_COOKIE in self._session.cookies

    # -- low-level helpers -------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _check(self, resp: HTTPResponse, method: str, path: str) -> None:
        if resp.status_code == 404:
            raise NotFoundError(
                f"{method} {path} returned 404 (not found)",
                status_code=resp.status_code,
                url=resp.url,
            )
        if resp.status_code >= 400:
            raise APIError(
                f"{method} {path} failed with HTTP {resp.status_code}",
                status_code=resp.status_code,
                url=resp.url,
            )

    def _get(self, path: str, **kwargs: Any) -> HTTPResponse:
        resp = self._session.get(self._url(path), timeout=self.timeout, **kwargs)
        self._check(resp, "GET", path)
        # If we were bounced to the login page, the session is not
        # authenticated — fail loudly instead of parsing the login HTML.
        final_path = urlparse(resp.url).path.rstrip("/")
        if path != "/login" and final_path == "/login":
            raise AuthError("not authenticated (request was redirected to /login)")
        return resp

    # -- auth ---------------------------------------------------------------

    def login(self, email: str, password: str) -> None:
        """Sign in with a regular Gradescope account (email + password, not SSO).

        Posts the same form the web login page uses. Raises :class:`AuthError`
        if the credentials are rejected.
        """
        login_page = self._session.get(self._url("/login"), timeout=self.timeout)
        self._check(login_page, "GET", "/login")
        token = parsers.extract_csrf_token(login_page.text)
        resp = self._session.post(
            self._url("/login"),
            data={
                "utf8": "✓",
                "authenticity_token": token,
                "session[email]": email,
                "session[password]": password,
                "session[remember_me]": "1",
                "commit": "Log In",
            },
            timeout=self.timeout,
            allow_redirects=False,
        )
        if resp.status_code in (301, 302, 303) or SESSION_COOKIE in self._session.cookies:
            self._logged_in = True
            self.email = email
            return
        raise AuthError(
            "Gradescope login failed for that email/password. Note: school (SAML) and "
            "Google SSO sign-in are not supported by this tool — use a regular Gradescope "
            "account (if your account is SSO-only, set a Gradescope password via "
            "'Forgot your password?' on the login page)."
        )

    def ensure_logged_in(self, email: str, password: str) -> None:
        if not self.is_authenticated:
            self.login(email, password)

    # -- browsing ------------------------------------------------------------

    def list_courses(self) -> list[Course]:
        """List all courses the account can see.

        Tries ``/account``, the homepage (course dashboard), then ``/courses``.
        """
        first_error: APIError | None = None
        got_page = False
        for path in ("/account", "/", "/courses"):
            try:
                page = self._get(path)
            except APIError as exc:  # includes NotFoundError
                first_error = first_error or exc
                continue
            got_page = True
            courses = parsers.parse_courses(page.text)
            if courses:
                return parsers.sort_courses_by_term(courses)
        if not got_page and first_error is not None:
            raise first_error
        return []

    def list_assignments(self, course_id: str) -> list[Assignment]:
        """List assignments (with due dates) for a course.

        Students: the course dashboard ``/courses/<id>`` has
        ``table#assignments-student-table``. Instructors (or newer layouts):
        ``/courses/<id>/assignments`` embeds a React ``AssignmentsTable``
        (students get 401 there — tolerated). Raises only if every page
        failed to load.
        """
        first_error: APIError | None = None
        got_page = False
        for path in (f"/courses/{course_id}", f"/courses/{course_id}/assignments"):
            try:
                page = self._get(path)
            except APIError as exc:  # includes NotFoundError; 401 on fallback
                first_error = first_error or exc
                continue
            got_page = True
            assignments = parsers.parse_assignments(page.text, course_id)
            if not assignments:
                assignments = parsers.parse_assignments_react(page.text, course_id)
            if assignments:
                return assignments
        if not got_page and first_error is not None:
            raise first_error
        return []

    # -- submissions ----------------------------------------------------------

    def submit(self, course_id: str, assignment_id: str, files: Sequence[str | Path]) -> Submission:
        """Upload files to an assignment and return the new submission."""
        if not files:
            raise ValueError("at least one file is required to submit")
        page = self._get(f"/courses/{course_id}/assignments/{assignment_id}")
        token = parsers.extract_csrf_token(page.text)
        path = f"/courses/{course_id}/assignments/{assignment_id}/submissions"
        with ExitStack() as stack:
            file_tuples: list[tuple[str, tuple[str, Any]]] = []
            for file in files:
                path_obj = Path(file)
                handle = stack.enter_context(path_obj.open("rb"))
                file_tuples.append(("submission[files][]", (path_obj.name, handle)))
            resp = self._session.post(
                self._url(path),
                data={"authenticity_token": token},
                files=file_tuples,
                timeout=self.timeout,
                allow_redirects=False,
            )
        if resp.status_code in (301, 302, 303):
            location = resp.headers.get("Location", "")
            submission_id = parsers.parse_submission_id(location)
            return Submission(
                id=submission_id,
                course_id=course_id,
                assignment_id=assignment_id,
                url=(
                    f"/courses/{course_id}/assignments/{assignment_id}/submissions/{submission_id}"
                ),
            )
        raise APIError(
            f"submission to assignment {assignment_id} failed with HTTP {resp.status_code}",
            status_code=resp.status_code,
            url=resp.url,
        )

    def list_submissions(self, course_id: str, assignment_id: str) -> list[Submission]:
        """List the account's submissions for an assignment (from its page)."""
        page = self._get(f"/courses/{course_id}/assignments/{assignment_id}")
        return parsers.parse_submissions(page.text, course_id, assignment_id)

    # -- autograder ------------------------------------------------------------

    def get_autograder_result(
        self, course_id: str, assignment_id: str, submission_id: str
    ) -> AutograderResult:
        """Fetch the current autograder status/results for a submission.

        Prefers the React JSON endpoint (``/submissions/<id>.json``), falling
        back to parsing the HTML submission page.
        """
        base = f"/courses/{course_id}/assignments/{assignment_id}/submissions/{submission_id}"
        try:
            resp = self._session.get(
                self._url(base + ".json"), params={"content": "react"}, timeout=self.timeout
            )
            if resp.status_code == 200:
                result = parsers.parse_submission_json(resp.json(), submission_id)
                if result is not None:
                    return result
        except (APIError, ValueError, NotImplementedError):
            pass  # JSON unavailable -> fall back to the HTML page
        page = self._get(base)
        status = parsers.parse_submission_status(page.text)
        return AutograderResult(
            submission_id=submission_id,
            status=status.status,
            score=status.score,
            max_score=status.max_score,
            test_cases=list(status.test_cases),
        )

    def wait_for_autograder(
        self,
        course_id: str,
        assignment_id: str,
        submission_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> AutograderResult:
        """Poll until the autograder finishes (status != "pending")."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.get_autograder_result(course_id, assignment_id, submission_id)
            if result.status != "pending":
                return result
            if time.monotonic() >= deadline:
                raise AutograderTimeoutError(
                    f"autograder for submission {submission_id} did not finish within {timeout:g}s"
                )
            sleep(poll_interval)

    # -- leaderboard -----------------------------------------------------------

    def get_leaderboard(self, course_id: str, assignment_id: str) -> list[LeaderboardEntry]:
        """Fetch the leaderboard for an assignment."""
        page = self._get(f"/courses/{course_id}/assignments/{assignment_id}/leaderboard")
        return parsers.parse_leaderboard(page.text)
