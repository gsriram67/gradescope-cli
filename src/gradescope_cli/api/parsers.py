"""Pure parsing functions: Gradescope HTML pages -> data models.

These functions never touch the network, which makes them easy to unit
test against fixture HTML.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from gradescope_cli.api.models import (
    Assignment,
    AutograderResult,
    Course,
    LeaderboardEntry,
    Submission,
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
    """Matches assignment links, including ``/assignments/<id>/submissions/<sid>``
    (past assignments on the student dashboard link straight to the latest
    submission page)."""
    return re.compile(rf"/courses/{re.escape(course_id)}/assignments/(\d+)")


_TERM_SEASON_RANK = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}
_TERM_RE = re.compile(r"^\s*(\w+)\s+(\d{4})\s*$")


def term_sort_key(term: str | None) -> tuple[int, int]:
    """Sort key for term labels like "Fall 2026" (academic year order)."""
    if not term:
        return (-1, -1)
    m = _TERM_RE.match(term)
    if m is None:
        return (-1, -1)
    return (int(m.group(2)), _TERM_SEASON_RANK.get(m.group(1).lower(), -1))


def sort_courses_by_term(courses: list[Course]) -> list[Course]:
    """Order courses by term, most recent first."""
    return sorted(courses, key=lambda c: term_sort_key(c.term), reverse=True)


_TERM_CODE_RE = re.compile(r"_(FA|WI|SP|SU)(\d{2})(?:_|$)")
_TERM_CODE_SEASON = {"FA": "Fall", "WI": "Winter", "SP": "Spring", "SU": "Summer"}


def _term_from_code(code: str | None) -> str | None:
    """Derive a term label from a course code like ``MATH173A_FA26_001``."""
    if not code:
        return None
    m = _TERM_CODE_RE.search(code)
    if m is None:
        return None
    return f"{_TERM_CODE_SEASON[m.group(1)]} {2000 + int(m.group(2))}"


def _term_for_course_box(box: Tag) -> str | None:
    """Find the term label (e.g. "Fall 2026") a courseBox belongs to.

    The term header is an ``h2.courseList--term`` sibling of the
    ``courseList--coursesForTerm`` container.
    """
    container = box.find_parent("div", class_="courseList--coursesForTerm")
    if container is None:
        return None
    term_el = container.find_previous_sibling(class_="courseList--term")
    if term_el is None:
        return None
    return term_el.get_text(strip=True) or None


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
        term = _term_for_course_box(a) or _term_from_code(code)
        count_el = a.find(class_="courseBox--assignments")
        num_assignments: int | None = None
        if count_el is not None:
            m_count = re.search(r"(\d+)", count_el.get_text())
            if m_count is not None:
                num_assignments = int(m_count.group(1))
        courses[course_id] = Course(
            id=course_id,
            name=name,
            code=code,
            term=term,
            num_assignments=num_assignments,
            url=f"/courses/{course_id}",
        )
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
        courses[course_id] = Course(
            id=course_id,
            name=name,
            code=code,
            term=_term_from_code(code),
            url=f"/courses/{course_id}",
        )
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


def _parse_time_datetime(tag: Tag) -> datetime | None:
    """Parse a ``<time datetime="...">`` attribute into a naive datetime."""
    raw = tag.get("datetime")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_submission_status_cell(row: Tag) -> tuple[str | None, float | None, float | None]:
    """Extract (status, score, max_score) from a student-table row.

    ``td.submissionStatus`` carries a ``submissionStatus-complete`` modifier
    when submitted, and a ``.submissionStatus--score`` div like "8.5 / 10"
    when graded.
    """
    cell = row.find("td", class_=lambda c: c is not None and "submissionStatus" in str(c))
    if cell is None:
        return None, None, None
    cls_attr = cell.get("class")
    classes = (
        " ".join(str(c) for c in cls_attr) if isinstance(cls_attr, list) else str(cls_attr or "")
    )
    score: float | None = None
    max_score: float | None = None
    score_el = cell.find(class_=lambda c: c is not None and "score" in str(c).lower())
    if score_el is not None:
        m = _SCORE.search(score_el.get_text(" ", strip=True))
        if m is not None:
            score = float(m.group(1))
            max_score = float(m.group(2))
    if score is not None:
        status = "graded"
    elif "complete" in classes:
        status = "submitted"
    else:
        status = "open"
    return status, score, max_score


def parse_assignments(html: str, course_id: str) -> list[Assignment]:
    """Parse a course page into its assignments.

    Handles, in order: the student dashboard table
    (``table#assignments-student-table`` with ``button[data-assignment-id]``
    titles and ``time.submissionTimeChart--dueDate`` dates), the older
    ``tr[role="row"]`` dashboard rows, ``th.table--primaryLink`` anchors, and
    finally any anchor pointing at ``/courses/<id>/assignments/<id>``.
    """
    soup = BeautifulSoup(html, "html.parser")
    href_re = _assignment_href(course_id)
    seen: set[str] = set()
    assignments: list[Assignment] = []

    def add(anchor: Tag, title: str, row: Tag | None) -> None:
        href = anchor["href"]
        if not isinstance(href, str):
            return
        m = href_re.search(href)
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

    # Student dashboard rows — in ANY table/section on the page (active and
    # past assignments may live in separate tables). The title cell holds a
    # <button data-assignment-id=...> (not an <a href>).
    for tr in soup.find_all("tr"):
        btn = tr.find(lambda tag: tag.has_attr("data-assignment-id"))
        if btn is not None:
            aid = str(btn["data-assignment-id"])
            title = btn.get_text(strip=True)
        else:
            th = tr.find("th", class_=lambda c: c is not None and "primaryLink" in str(c))
            if th is None:
                continue
            a = th.find("a", href=True)
            if a is None:
                continue
            href = a["href"]
            if not isinstance(href, str):
                continue
            m = href_re.search(href)
            if m is None:
                continue
            aid, title = m.group(1), th.get_text(" ", strip=True)
        if aid in seen or not title:
            continue
        seen.add(aid)
        due_dates = [
            d
            for t in tr.find_all("time", class_=lambda c: c is not None and "dueDate" in str(c))
            if (d := _parse_time_datetime(t)) is not None
        ]
        due_date = max(due_dates) if due_dates else _find_due_date_in(tr)
        status, score, max_score = _parse_submission_status_cell(tr)
        assignments.append(
            Assignment(
                id=aid,
                course_id=course_id,
                title=title,
                due_date=due_date,
                status=status,
                score=score,
                max_score=max_score,
                url=f"/courses/{course_id}/assignments/{aid}",
            )
        )
    if assignments:
        return assignments

    # Older dashboard markup: rows tr[role="row"]; first cell holds the link.
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


def parse_assignments_react(html: str, course_id: str) -> list[Assignment]:
    """Parse the instructor ``/assignments`` page.

    That page embeds a React table: ``div[data-react-class="AssignmentsTable"]``
    with a JSON ``data-react-props`` payload containing ``table_data``.
    (Students get a 401 on this page; they use the dashboard table instead.)
    """
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", attrs={"data-react-class": "AssignmentsTable"})
    if div is None:
        return []
    raw = div.get("data-react-props")
    if not isinstance(raw, str):
        return []
    try:
        props = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(props, dict):
        return []
    assignments: list[Assignment] = []
    for row in props.get("table_data", []):
        if not isinstance(row, dict):
            continue
        aid = str(row.get("id") or "")
        title = str(row.get("title") or "")
        if not aid or not title:
            continue
        due_date: datetime | None = None
        window = row.get("submission_window")
        if isinstance(window, dict):
            raw_due = window.get("due_date") or window.get("hard_due_date")
            if isinstance(raw_due, str):
                try:
                    due_date = datetime.fromisoformat(raw_due).replace(tzinfo=None)
                except ValueError:
                    due_date = None
        status = "submitted" if row.get("student_submission") else "open"
        max_score = _as_float(row.get("total_points"))
        url = row.get("url")
        assignments.append(
            Assignment(
                id=aid,
                course_id=course_id,
                title=title,
                due_date=due_date,
                status=status,
                max_score=max_score,
                url=url
                if isinstance(url, str) and url
                else f"/courses/{course_id}/assignments/{aid}",
            )
        )
    return assignments


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def parse_submission_json(data: Any, submission_id: str) -> AutograderResult | None:
    """Parse the React submission JSON (``/submissions/<id>.json?content=react``).

    Returns ``None`` when the payload has no score data (e.g. still pending
    or an unexpected shape), so callers can fall back to HTML scraping.
    """
    if not isinstance(data, dict):
        return None
    nested = data.get("submission")
    src: dict[str, Any] = nested if isinstance(nested, dict) else data
    score = _as_float(src.get("score"))
    max_score = _as_float(src.get("max_score"))
    if score is None and max_score is None:
        return None
    raw_status = str(src.get("status") or ("graded" if score is not None else "pending")).lower()
    if raw_status in {"graded", "complete", "completed"} or score is not None:
        status = "graded"
    elif raw_status in {"error", "failed"}:
        status = "error"
    else:
        status = "pending"
    test_cases: list[TestCaseResult] = []
    questions = src.get("submission_questions") or src.get("questions") or []
    if isinstance(questions, list):
        for q in questions:
            if not isinstance(q, dict):
                continue
            name = q.get("name") or q.get("title")
            if name is None and q.get("question_number") is not None:
                name = f"Question {q['question_number']}"
            name = str(name or "")
            q_score = _as_float(q.get("score"))
            q_max = _as_float(q.get("max_score"))
            if q_score is not None and q_max is not None and q_max > 0:
                case_status = "passed" if q_score >= q_max else "failed"
            else:
                case_status = "unknown"
            test_cases.append(
                TestCaseResult(name=name, score=q_score, max_score=q_max, status=case_status)
            )
    return AutograderResult(
        submission_id=submission_id,
        status=status,
        score=score,
        max_score=max_score,
        test_cases=test_cases,
    )


def parse_submissions(html: str, course_id: str, assignment_id: str) -> list[Submission]:
    """Parse an assignment page's "your submissions" list.

    Finds anchors to ``/courses/<cid>/assignments/<aid>/submissions/<id>`` and
    pulls the submitted time (``<time datetime>`` or any date cell) and score
    from the surrounding row.
    """
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(
        rf"/courses/{re.escape(course_id)}/assignments/{re.escape(assignment_id)}/submissions/(\d+)"
    )
    seen: set[str] = set()
    result: list[Submission] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not isinstance(href, str):
            continue
        m = pattern.search(href)
        if m is None:
            continue
        submission_id = m.group(1)
        if submission_id in seen:
            continue
        seen.add(submission_id)
        submitted_at: datetime | None = None
        score: float | None = None
        row = a.find_parent("tr") or a.find_parent("li")
        if isinstance(row, Tag):
            time_el = row.find("time")
            if time_el is not None:
                submitted_at = _parse_time_datetime(time_el)
            if submitted_at is None:
                submitted_at = _find_due_date_in(row)
            score_el = row.find(class_=lambda c: c is not None and "score" in str(c).lower())
            if score_el is not None:
                sm = _SCORE.search(score_el.get_text(" ", strip=True))
                if sm is not None:
                    score = float(sm.group(1))
        result.append(
            Submission(
                id=submission_id,
                course_id=course_id,
                assignment_id=assignment_id,
                submitted_at=submitted_at,
                score=score,
                status="graded" if score is not None else "submitted",
                url=f"/courses/{course_id}/assignments/{assignment_id}/submissions/{submission_id}",
            )
        )
    return result


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


_LB_TASK_KEY = re.compile(r"^task \d+$")


def parse_leaderboard_react(html: str) -> list[LeaderboardEntry]:
    """Parse the React leaderboard (``div[data-react-class="Leaderboard"]``).

    Props contain ``entries``: ``{"name": ..., "assignment_submission_id": ...,
    "task N": score, ...}``. An entry's score is the sum of its public task
    scores; rank is its position in the list.
    """
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", attrs={"data-react-class": "Leaderboard"})
    if div is None:
        return []
    raw = div.get("data-react-props")
    if not isinstance(raw, str):
        return []
    try:
        props = json.loads(raw)
    except json.JSONDecodeError:
        return []
    entries = props.get("entries") if isinstance(props, dict) else None
    if not isinstance(entries, list):
        return []
    result: list[LeaderboardEntry] = []
    for rank, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        score = 0.0
        for key, value in entry.items():
            if _LB_TASK_KEY.match(str(key)) and isinstance(value, (int, float)):
                score += float(value)
        sid = entry.get("assignment_submission_id")
        result.append(
            LeaderboardEntry(
                rank=rank,
                name=name,
                score=score,
                submission_id=str(sid) if sid is not None else None,
            )
        )
    return result


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
