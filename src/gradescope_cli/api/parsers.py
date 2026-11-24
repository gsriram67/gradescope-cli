"""Pure parsing functions: Gradescope HTML pages -> data models.

These functions never touch the network, which makes them easy to unit
test against fixture HTML.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup
from bs4.element import Tag

from gradescope_cli.api.models import (
    Assignment,
    Course,
    LeaderboardEntry,
    SubmissionStatus,
    TestCaseResult,
)
from gradescope_cli.exceptions import ParseError

_COURSE_HREF = re.compile(r"^(?:https?://[^/]+)?/courses/(\d+)/?(?:[?#].*)?$")
_SUBMISSION_HREF = re.compile(r"submissions/(\d+)")
_SCORE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")
# Trailing timezone abbreviation, e.g. the "PDT" in "Nov 25, 2026 at 11:59pm PDT".
_TZ_SUFFIX = re.compile(r"\s+[A-Za-z]{2,5}$")

_DUE_DATE_FORMATS = (
    "%b %d, %Y at %I:%M%p",
    "%b %d at %I:%M%p",
    "%B %d, %Y at %I:%M%p",
    "%B %d at %I:%M%p",
    "%b %d, %Y %I:%M%p",
    "%Y-%m-%d %H:%M:%S %z",  # dashboard cells, e.g. "2026-11-25 23:59:00 -0800"
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def parse_due_date(text: str, *, now: datetime | None = None) -> datetime | None:
    """Parse a Gradescope date string, returning ``None`` if unrecognized.

    Yearless dates (e.g. "Dec 5 at 9:00am") are resolved to the next
    occurrence relative to ``now`` (defaults to the current time).
    Timezone-aware results are normalized to naive local datetimes.
    """
    now = now or datetime.now()
    cleaned = _TZ_SUFFIX.sub("", " ".join(text.split()))
    for fmt in _DUE_DATE_FORMATS:
        if "%Y" in fmt:
            candidates = [(cleaned, fmt)]
        else:
            # Yearless dates (e.g. "Dec 5 at 9:00am"): try the current and
            # next year. Always parse with an explicit year to stay
            # compatible with Python >= 3.15 strptime behavior.
            candidates = [(f"{cleaned} {year}", f"{fmt} %Y") for year in (now.year, now.year + 1)]
        for text, full_fmt in candidates:
            try:
                parsed = datetime.strptime(text, full_fmt)
            except ValueError:
                continue
            if "%Y" not in fmt and parsed < now:
                continue  # already past; try next year
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
    return None


def extract_csrf_token(html: str) -> str:
    """Extract the Rails ``authenticity_token`` hidden input from a form page."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("input", attrs={"name": "authenticity_token"})
    if tag is None or not tag.get("value"):
        raise ParseError("could not find authenticity_token in page")
    return str(tag["value"])


def _assignment_href(course_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"^(?:https?://[^/]+)?/courses/{re.escape(course_id)}/assignments/(\d+)/?(?:[?#].*)?$"
    )


def parse_courses(html: str) -> list[Course]:
    """Parse a courses page into a de-duplicated list of courses.

    Handles the current ``/account`` markup (``a.courseBox`` with an ``h3``
    name) and falls back to any anchor pointing at ``/courses/<id>``.
    """
    soup = BeautifulSoup(html, "html.parser")
    courses: dict[str, Course] = {}

    # Current markup: course boxes on the /account page.
    for a in soup.find_all("a", class_="courseBox", href=True):
        href = a["href"]
        if not isinstance(href, str):
            continue
        m = _COURSE_HREF.match(href)
        if m is None:
            continue
        course_id = m.group(1)
        if course_id in courses:
            continue
        # courseBox: div.courseBox--name = full name, h3.courseBox--shortname = code
        name_el = a.find("div", class_="courseBox--name") or a.find("h3")
        name = name_el.get_text(strip=True) if name_el is not None else a.get_text(strip=True)
        if not name:
            continue
        code: str | None = None
        code_el = a.find("h3", class_="courseBox--shortname") or a.find(
            class_=lambda c: c is not None and "short" in str(c).lower()
        )
        if code_el is not None:
            code = code_el.get_text(strip=True) or None
        courses[course_id] = Course(id=course_id, name=name, code=code, url=f"/courses/{course_id}")
    if courses:
        return list(courses.values())

    # Fallback: any anchor pointing at /courses/<id>.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not isinstance(href, str):
            continue
        m = _COURSE_HREF.match(href)
        if m is None:
            continue
        course_id = m.group(1)
        name = a.get_text(strip=True)
        if course_id in courses or not name:
            continue
        code = None
        card = a.find_parent("div")
        if card is not None:
            code_el = card.find(class_=lambda c: c is not None and "code" in str(c).lower())
            if code_el is not None:
                code = code_el.get_text(strip=True) or None
        courses[course_id] = Course(id=course_id, name=name, code=code, url=f"/courses/{course_id}")
    return list(courses.values())


def _find_due_date_in(row: Tag) -> datetime | None:
    """Find the due date inside a table row / list item.

    Dashboard rows contain both an open and a close/due date, so the latest
    parseable date in the row wins. ``<time datetime="...">`` attributes are
    also honored.
    """
    dates: list[datetime] = []
    for time_el in row.find_all("time"):
        raw = time_el.get("datetime")
        if isinstance(raw, str):
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                continue
            dates.append(parsed.replace(tzinfo=None))
    due_cells = row.find_all(class_=lambda c: c is not None and "due" in str(c).lower())
    for el in [*due_cells, *row.find_all(["td", "th", "span", "div"])]:
        cell_date = parse_due_date(el.get_text(" ", strip=True))
        if cell_date is not None:
            dates.append(cell_date)
    return max(dates) if dates else None


def parse_assignments(html: str, course_id: str) -> list[Assignment]:
    """Parse a course page into its assignments.

    Handles the current course-dashboard markup (``tr[role="row"]`` rows whose
    first cell links to ``/courses/<id>/assignments/<id>``), then
    ``th.table--primaryLink``, then falls back to any matching anchor.
    """
    soup = BeautifulSoup(html, "html.parser")
    href_re = _assignment_href(course_id)
    seen: set[str] = set()
    assignments: list[Assignment] = []

    def add(anchor: Tag, title: str, row: Tag | None) -> None:
        href = anchor["href"]
        if not isinstance(href, str):
            return
        m = href_re.match(href)
        if m is None:
            return
        assignment_id = m.group(1)
        if assignment_id in seen or not title:
            return
        seen.add(assignment_id)
        due_date: datetime | None = None
        if row is not None:
            due_date = _find_due_date_in(row)
        assignments.append(
            Assignment(
                id=assignment_id,
                course_id=course_id,
                title=title,
                due_date=due_date,
                url=f"/courses/{course_id}/assignments/{assignment_id}",
            )
        )

    # Current markup: dashboard rows tr[role="row"]; first cell holds the link.
    for tr in soup.find_all("tr", attrs={"role": "row"}):
        cells = [*tr.find_all("th"), *tr.find_all("td")]
        if not cells:
            continue
        first = cells[0]
        a = first.find("a", href=True)
        if a is not None:
            add(a, first.get_text(" ", strip=True), tr)
    if assignments:
        return assignments

    # Older markup: th.table--primaryLink > a.
    for th in soup.find_all("th", class_=lambda c: c is not None and "primaryLink" in str(c)):
        a = th.find("a", href=True)
        if a is not None:
            add(a, th.get_text(" ", strip=True), th.find_parent("tr"))
    if assignments:
        return assignments

    # Fallback: any anchor to /courses/<id>/assignments/<id>.
    for a in soup.find_all("a", href=True):
        row = a.find_parent("tr") or a.find_parent("li") or a.parent
        add(a, a.get_text(strip=True), row if isinstance(row, Tag) else None)
    return assignments


def parse_submission_id(location: str) -> str:
    """Extract the submission id from a redirect ``Location`` header."""
    m = _SUBMISSION_HREF.search(location)
    if m is None:
        raise ParseError(f"could not find a submission id in redirect {location!r}")
    return m.group(1)


def parse_submission_status(html: str) -> SubmissionStatus:
    """Parse a submission page into its autograder status."""
    soup = BeautifulSoup(html, "html.parser")
    status_el = soup.find(lambda tag: tag.has_attr("data-status"))
    raw = str(status_el["data-status"]).lower() if status_el is not None else ""
    if raw in {"graded", "complete", "completed", "done"}:
        status = "graded"
    elif raw in {"error", "failed"}:
        status = "error"
    else:
        status = "pending"

    score: float | None = None
    max_score: float | None = None
    score_el = soup.select_one(".submission-score")
    if score_el is not None:
        m = _SCORE.search(score_el.get_text(" ", strip=True))
        if m is not None:
            score = float(m.group(1))
            max_score = float(m.group(2))

    test_cases: list[TestCaseResult] = []
    for tr in soup.select("tr.test-case"):
        name_el = tr.select_one(".test-name")
        score_el = tr.select_one(".test-score")
        name = name_el.get_text(strip=True) if name_el is not None else ""
        case_score: float | None = None
        case_max: float | None = None
        if score_el is not None:
            m = _SCORE.search(score_el.get_text(" ", strip=True))
            if m is not None:
                case_score = float(m.group(1))
                case_max = float(m.group(2))
        cls_attr = tr.get("class")
        if isinstance(cls_attr, list):
            classes = " ".join(str(c) for c in cls_attr)
        else:
            classes = str(cls_attr or "")
        case_status = (
            "passed" if "passed" in classes else "failed" if "failed" in classes else "unknown"
        )
        test_cases.append(
            TestCaseResult(name=name, score=case_score, max_score=case_max, status=case_status)
        )

    return SubmissionStatus(
        status=status, score=score, max_score=max_score, test_cases=tuple(test_cases)
    )


def parse_leaderboard(html: str) -> list[LeaderboardEntry]:
    """Parse an assignment's ``/leaderboard`` page."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_=lambda c: c is not None and "leaderboard" in str(c).lower())
    if table is None:
        raise ParseError("no leaderboard table found on page")
    entries: list[LeaderboardEntry] = []
    for tr in table.find_all("tr"):
        rank_el = tr.select_one(".rank")
        name_el = tr.select_one(".name")
        score_el = tr.select_one(".score")
        if rank_el is None or name_el is None or score_el is None:
            continue  # header row
        try:
            rank = int(rank_el.get_text(strip=True))
            score = float(score_el.get_text(strip=True).rstrip("%"))
        except ValueError:
            continue
        link = tr.select_one("a[href*='submissions/']")
        submission_id = None
        if link is not None:
            m = _SUBMISSION_HREF.search(str(link["href"]))
            if m is not None:
                submission_id = m.group(1)
        entries.append(
            LeaderboardEntry(
                rank=rank,
                name=name_el.get_text(strip=True),
                score=score,
                submission_id=submission_id,
            )
        )
    return entries
