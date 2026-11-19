from __future__ import annotations

import pytest

from gradescope_cli.api.client import GradescopeClient
from tests.fixtures import FakeSession

TEST_BASE_URL = "https://gradescope.test"


@pytest.fixture
def session() -> FakeSession:
    return FakeSession(base_url=TEST_BASE_URL)


@pytest.fixture
def client(session: FakeSession) -> GradescopeClient:
    return GradescopeClient(session=session, base_url=TEST_BASE_URL)
