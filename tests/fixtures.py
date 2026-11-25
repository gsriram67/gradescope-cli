"""Shared test fixtures: fake HTTP session and sample Gradescope HTML pages."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Sample HTML pages (modeled on Gradescope's markup)
# ---------------------------------------------------------------------------

LOGIN_PAGE = """
<html><body>
  <form action="/login" method="post">
    <input type="hidden" name="authenticity_token" value="tok-login-123" />
    <input type="email" name="session[email]" />
    <input type="password" name="session[password]" />
  </form>
</body></html>
"""

LOGIN_PAGE_FAILED = """
<html><body>
  <div class="flash-error">Invalid email or password.</div>
  <form action="/login" method="post">
    <input type="hidden" name="authenticity_token" value="tok-login-123" />
  </form>
</body></html>
"""

ACCOUNT_PAGE = """
<html><body>
  <h1 class="pageHeading">Course Dashboard</h1>
  <div id="account-show">
    <div class="courseList">
      <h2 class="courseList--term">Spring 2026</h2>
      <div class="courseList--coursesForTerm">
        <a class="courseBox" href="/courses/111">
          <h3 class="courseBox--shortname">DSC 190</h3>
          <div class="courseBox--name">DSC 190 - Capstone Project</div>
          <div class="courseBox--assignments"><div class="left">7 assignments</div></div>
        </a>
      </div>
      <h2 class="courseList--term">Fall 2026</h2>
      <div class="courseList--coursesForTerm">
        <a class="courseBox" href="https://www.gradescope.com/courses/222">
          <h3 class="courseBox--shortname">CSE 151A</h3>
          <div class="courseBox--name">CSE 151A - Intro to ML</div>
        </a>
      </div>
    </div>
  </div>
</body></html>
"""

DASHBOARD_PAGE = """
<html><body>
  <table id="assignments-student-table">
    <tbody>
      <tr role="row">
        <th role="columnheader" scope="col">Name</th>
        <th role="columnheader" scope="col">Status</th>
        <th role="columnheader" scope="col">Due</th>
      </tr>
      <tr role="row">
        <th class="table--primaryLink" role="rowheader" scope="row">
          <a aria-label="View Homework 1"
             href="/courses/111/assignments/8797872/submissions/435388014">Homework 1</a>
        </th>
        <td class="submissionStatus"><div class="submissionStatus--score">100.0 / 100.0</div></td>
        <td><div class="submissionTimeChart">
          <time class="submissionTimeChart--releaseDate"
                datetime="2026-10-02 15:53:00 -0700"></time>
          <time class="submissionTimeChart--dueDate"
                datetime="2026-10-13 05:00:00 -0700"></time>
        </div></td>
      </tr>
      <tr role="row">
        <th class="table--primaryLink" role="rowheader" scope="row">
          <a href="/courses/111/assignments/8859109/submissions/438001592">Homework 2</a>
        </th>
        <td class="submissionStatus submissionStatus-complete">
          <div class="submissionStatus--score">98.0 / 100.0</div>
        </td>
        <td>
          <time class="submissionTimeChart--dueDate"
                datetime="2026-10-20 05:00:00 -0700"></time>
        </td>
      </tr>
      <tr role="row">
        <th class="table--primaryLink">
          <button data-assignment-id="9113089"
                  data-post-url="/courses/111/assignments/9113089/submissions">Homework 7</button>
        </th>
        <td class="submissionStatus"></td>
        <td>
          <time class="submissionTimeChart--dueDate"
                datetime="2026-12-03T17:00:00-08:00"></time>
        </td>
      </tr>
    </tbody>
  </table>
</body></html>
"""

ASSIGNMENTS_REACT_PAGE = """
<html><body>
  <div data-react-class="AssignmentsTable"
       data-react-props='{"table_data": [
         {"id": 777, "title": "Homework 1", "url": "/courses/111/assignments/777",
          "student_submission": true, "total_points": "10.0",
          "submission_window": {"release_date": "2026-11-01T00:00:00-07:00",
                                "due_date": "2026-11-25T23:59:00-08:00"}},
         {"id": 888, "title": "Homework 2", "url": "/courses/111/assignments/888",
          "student_submission": false, "total_points": "10.0",
          "submission_window": {"due_date": "2026-12-05T09:00:00-08:00"}},
         {"id": 999, "title": "Extra credit", "url": "/courses/111/assignments/999"}
       ]}'></div>
</body></html>
"""

COURSES_PAGE = """
<html><body>
  <div class="course-card">
    <a class="course-card--name" href="/courses/111">DSC 190 - Capstone Project</a>
    <span class="course-card--code">DSC 190</span>
    <a href="/courses/111">Submit code</a>
  </div>
  <div class="course-card">
    <a class="course-card--name" href="https://www.gradescope.com/courses/222">CSE 151A</a>
    <span class="course-card--code">CSE 151A</span>
  </div>
</body></html>
"""

ASSIGNMENTS_PAGE = """
<html><body>
  <table class="assignments-table">
    <tr>
      <td><a href="/courses/111/assignments/777">Homework 1</a></td>
      <td class="due-date">Nov 25, 2026 at 11:59pm PDT</td>
    </tr>
    <tr>
      <td><a href="/courses/111/assignments/888">Homework 2</a></td>
      <td class="due-date">Dec 5 at 9:00am</td>
    </tr>
    <tr>
      <td><a href="/courses/111/assignments/999">Extra credit</a></td>
      <td class="due-date">no due date</td>
    </tr>
  </table>
</body></html>
"""

ASSIGNMENT_PAGE = """
<html><body>
  <form action="/courses/111/assignments/777/submissions" method="post"
        enctype="multipart/form-data">
    <input type="hidden" name="authenticity_token" value="tok-submit-456" />
    <input type="file" name="submission[files][]" multiple />
  </form>
  <table class="submissions-table">
    <tr>
      <td><a href="/courses/111/assignments/777/submissions/999">Submission #999</a></td>
      <td><time datetime="2026-11-24T10:00:00-08:00"></time></td>
      <td class="submissionStatus--score">8.5 / 10</td>
    </tr>
    <tr>
      <td><a href="/courses/111/assignments/777/submissions/998">Submission #998</a></td>
      <td><time datetime="2026-11-23T09:00:00-08:00"></time></td>
      <td></td>
    </tr>
  </table>
  <div data-react-class="AssignmentSubmissionViewer"
       data-react-props='{"assignment_submission": {"id": 999,
            "created_at": "2026-11-24T10:00:00.000000-08:00", "status": "processed",
            "score": "8.5"},
          "paths": {"submission_path": "/courses/111/assignments/777/submissions/999",
                    "submission_react_path":
                        "/courses/111/assignments/777/submissions/999.json?content=react"}}'>
  </div>
</body></html>
"""

SUBMISSION_PAGE_PENDING = """
<html><body>
  <div class="submission-status" data-status="pending">Autograder is running...</div>
</body></html>
"""

SUBMISSION_PAGE_GRADED = """
<html><body>
  <div class="submission-status" data-status="graded">Autograder Results</div>
  <div class="submission-score">
    <span class="score">8.5</span> / <span class="max-score">10</span>
  </div>
  <table class="autograder-results">
    <tr class="test-case passed">
      <td class="test-name">test_basic</td><td class="test-score">5 / 5</td>
    </tr>
    <tr class="test-case failed">
      <td class="test-name">test_edge_case</td><td class="test-score">3.5 / 5</td>
    </tr>
  </table>
</body></html>
"""

LEADERBOARD_REACT_PAGE = """
<html><body>
  <div data-react-class="Leaderboard"
       data-react-props='{"columns": [{"name": "task 1", "order": "desc"},
                                       {"name": "task 2", "order": "desc"}],
                           "entries": [
                             {"name": "Alice", "assignment_submission_id": 1001,
                              "task 1": 90.5, "task 1 (private)": 90.5, "task 2": 9.0},
                             {"name": "Bob", "assignment_submission_id": 1002,
                              "task 1": 80.0, "task 2": null}
                           ]}'>
  </div>
</body></html>
"""

LEADERBOARD_PAGE = """
<html><body>
  <table class="leaderboard-table">
    <tr><th>Rank</th><th>Name</th><th>Score</th></tr>
    <tr>
      <td class="rank">1</td>
      <td class="name"><a href="/courses/111/assignments/777/submissions/1001">Alice</a></td>
      <td class="score">99.5</td>
    </tr>
    <tr>
      <td class="rank">2</td>
      <td class="name">Bob</td>
      <td class="score">87</td>
    </tr>
  </table>
</body></html>
"""

# ---------------------------------------------------------------------------
# Fake HTTP layer
# ---------------------------------------------------------------------------


class FakeResponse:
    """Duck-typed stand-in for ``requests.Response``."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        url: str = "",
        headers: dict[str, str] | None = None,
        json_data: Any = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = headers or {}
        self.json_data = json_data

    def json(self) -> Any:
        if self.json_data is None:
            raise ValueError("no JSON body")
        return self.json_data


RouteHandler = Callable[..., FakeResponse]


class FakeSession:
    """Duck-typed stand-in for ``requests.Session`` with route table + logging."""

    def __init__(self, base_url: str = "https://gradescope.test") -> None:
        self.base_url = base_url
        self.cookies: dict[str, str] = {}
        self.routes: dict[tuple[str, str], FakeResponse | RouteHandler] = {}
        self.requests: list[dict[str, Any]] = []

    def add(self, method: str, path: str, response: FakeResponse | RouteHandler) -> None:
        self.routes[(method.upper(), path)] = response

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        path = url.removeprefix(self.base_url)
        handler = self.routes.get((method, path))
        if handler is None:
            return FakeResponse(status_code=404, text="not found", url=url)
        resp = handler(**kwargs) if callable(handler) else handler
        if not resp.url:  # handlers may preset url to simulate redirects
            resp.url = url
        return resp

    def last_request(self, method: str | None = None) -> dict[str, Any]:
        for req in reversed(self.requests):
            if method is None or req["method"] == method:
                result: dict[str, Any] = req
                return result
        raise AssertionError(f"no {method or ''} request recorded")
