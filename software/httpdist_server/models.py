from pydantic import BaseModel
from typing import Literal


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


class TestReport(str):
    """Represents a pytest TestReport as a cloudpickled and base64 encoded object"""


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
