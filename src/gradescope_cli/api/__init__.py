"""Backend that interfaces with the Gradescope web API."""

from gradescope_cli.api.client import BASE_URL, GradescopeAPI, GradescopeClient
from gradescope_cli.api.models import (
    Assignment,
    AutograderResult,
    Course,
    LeaderboardEntry,
    Submission,
    SubmissionStatus,
    TestCaseResult,
)

__all__ = [
    "BASE_URL",
    "Assignment",
    "AutograderResult",
    "Course",
    "GradescopeAPI",
    "GradescopeClient",
    "LeaderboardEntry",
    "Submission",
    "SubmissionStatus",
    "TestCaseResult",
]
