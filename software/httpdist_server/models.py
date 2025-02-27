from enum import StrEnum, auto
from pydantic import BaseModel

NodeId = str
SessionId = str


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


class SuccessResponse(BaseModel):
    message: str


class SessionResponse(BaseModel):
    """Response to a request to start a new session"""

    session_id: SessionId | None


class NoSessionResponse(BaseModel):
    """Indicates no session available for the worker"""

    pass


class TestsResponse(BaseModel):
    statuses: dict[NodeId, list[TestPhase]]


class TestReportResponse(BaseModel):
    report: str


class WorkerActionResponse(BaseModel):
    action: WorkerAction
    test_now: str | None
    test_next: str | None


class ArtifactListResponse(BaseModel):
    artifact_ids: list[str]


class WorkerRequirements(BaseModel):
    tags: set[str]


class SubmitTestsRequest(BaseModel):
    class Test(BaseModel):
        worker_requirements: list[WorkerRequirements]
        nodeid: NodeId

    tests: list[Test]


class TestReportRequest(BaseModel):
    nodeid: NodeId


class SubmitTestReportRequest(BaseModel):
    nodeid: NodeId
    phase: TestPhase
    report: str


class WorkerRegisterRequest(BaseModel):
    worker_id: str


class WorkerUpdateRequest(BaseModel):
    pet_name: str
    tags: list[str]


class WorkerInfoResponse(BaseModel):
    worker_id: str
    pet_name: str
    tags: list[str]


class ArtifactUploadRequest(BaseModel):
    worker_id: str
    content: str
