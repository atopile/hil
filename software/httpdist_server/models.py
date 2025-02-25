import cloudpickle
from pydantic import BaseModel
from typing import Literal

import pytest


class GetSessionResponse(BaseModel):
    """Response to a request to start a new session"""

    session_id: str


class PostSessionsTestsRequest(BaseModel):
    class Test(BaseModel):
        worker_requirements: set[str]
        node_id: str

    tests: list[Test]


class GetSessionTestsResponse(BaseModel):
    test_status: dict[str, Literal["pending", "running", "finished"]]


class TestReport(bytes):
    @staticmethod
    def from_report(report: pytest.TestReport) -> "TestReport":
        return TestReport(cloudpickle.dumps(report))

    def as_report(self) -> pytest.TestReport:
        return cloudpickle.loads(self)


class PostWorkerRegisterRequest(BaseModel):
    worker_id: str
    pet_name: str
    tags: list[str]


class PostWorkerSessionTestReportRequest(BaseModel):
    report: bytes


class GetWorkerSessionTestsResponse(BaseModel):
    action: Literal["run", "stop"]
    test_now: str | None
    test_next: str | None
