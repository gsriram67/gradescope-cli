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
  <a class="courseBox" href="/courses/111">
    <h3>DSC 190 - Capstone Project</h3>
    <span class="courseBox--shortName">DSC 190</span>
  </a>
  <a class="courseBox" href="https://www.gradescope.com/courses/222">
    <h3>CSE 151A</h3>
    <span class="courseBox--shortName">CSE 151A</span>
  </a>
</body></html>
"""

DASHBOARD_PAGE = """
<html><body>
  <table class="table">
    <tr>
      <th class="table--primaryLink"><a href="/courses/111/assignments/777">Homework 1</a></th>
      <td class="due-date">Nov 25, 2026 at 11:59pm PDT</td>
    </tr>
    <tr>
      <th class="table--primaryLink"><a href="/courses/111/assignments/888">Homework 2</a></th>
      <td class="due-date">Dec 5 at 9:00am</td>
    </tr>
    <tr>
      <th class="table--primaryLink"><a href="/courses/111/assignments/999">Extra credit</a></th>
      <td class="due-date">no due date</td>
    </tr>
  </table>
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
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = headers or {}

    def json(self) -> Any:
        raise NotImplementedError


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
