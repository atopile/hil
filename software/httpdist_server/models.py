from enum import StrEnum, auto
from pydantic import BaseModel

NodeId = str


class TestStatus(StrEnum):
    Pending = auto()
    Running = auto()
    Finished = auto()


class TestPhase(StrEnum):
    Setup = auto()
    Call = auto()
    Teardown = auto()


class SessionState(StrEnum):
    Setup = auto()
    Running = auto()
    Stopped = auto()


class WorkerAction(StrEnum):
    Run = auto()
    Stop = auto()


class GetSessionResponse(BaseModel):
    """Response to a request to start a new session"""

    session_id: str


class PostSessionsTestsRequest(BaseModel):
    class Test(BaseModel):
        worker_requirements: set[str]
        node_id: str

    tests: list[Test]


class GetSessionTestsResponse(BaseModel):
    test_status: dict[NodeId, list[TestPhase]]


class PostWorkerRegisterRequest(BaseModel):
    worker_id: str
    pet_name: str
    tags: list[str]


class GetSessionTestReportRequest(BaseModel):
    node_id: str


class PostWorkerSessionTestReportRequest(BaseModel):
    node_id: str
    phase: TestPhase
    report: str


class GetWorkerSessionTestsResponse(BaseModel):
    action: WorkerAction
    test_now: str | None
    test_next: str | None
