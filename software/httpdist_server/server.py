import logging
import base64
from dataclasses import dataclass, field
import uuid

import fastapi
import uvicorn
from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from httpdist_server.models import (
    ArtifactListResponse,
    ArtifactUploadRequest,
    NoSessionResponse,
    SessionResponse,
    SessionState,
    SubmitTestReportRequest,
    SubmitTestsRequest,
    SuccessResponse,
    TestPhase,
    TestReportRequest,
    TestReportResponse,
    TestStatus,
    NodeId,
    TestsResponse,
    WorkerAction,
    WorkerActionResponse,
)

logger = logging.getLogger(__name__)

app = fastapi.FastAPI()


@dataclass
class Worker:
    worker_id: str  # Typically the worker's mac address
    pet_name: str
    tags: set[str]


@dataclass
class Session:
    @dataclass
    class Test:
        worker_requirements: set[str]
        nodeid: NodeId

        status: TestStatus = TestStatus.Pending
        assigned_worker: Worker | None = None
        reports: dict[TestPhase, str | None] = field(
            default_factory=lambda: {
                TestPhase.Setup: None,
                TestPhase.Call: None,
                TestPhase.Teardown: None,
            }
        )

    session_id: str

    state: SessionState = SessionState.Setup
    tests: dict[str, Test] = field(default_factory=dict)
    env: UploadFile | None = None
    artifacts: dict[str, bytes] = field(default_factory=dict)

    async def stop(self):
        self.state = SessionState.Stopped
        if self.env is not None:
            await self.env.close()


# TODO: stick this in a database or something
sessions: dict[str, Session] = {
    "test-session": Session(
        session_id="test-session",
        tests={
            "tests/test_nothing.py::test_nothing": Session.Test(
                nodeid="tests/test_nothing.py::test_nothing",
                worker_requirements={"cellsim"},
            ),
            "tests/test_nothing.py::test_fail": Session.Test(
                nodeid="tests/test_nothing.py::test_fail",
                worker_requirements={"cellsim"},
            ),
        },
    ),
}
workers: list[Worker] = [
    Worker(
        worker_id="2ccf6728745b",
        pet_name="chunky-otter",
        tags={"cellsim"},
    )
]


@app.get("/")
async def root():
    return {"message": "Hello World!"}


@app.get("/session")
async def start_session() -> SessionResponse:
    session_id = str(uuid.uuid4())
    sessions[session_id] = Session(session_id=session_id)
    return SessionResponse(session_id=session_id)


@app.post("/session/{session_id}/stop")
async def stop_session(session_id: str) -> SuccessResponse:
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    await sessions[session_id].stop()

    return SuccessResponse(message="Stop signal sent")


@app.post("/session/{session_id}/env")
async def submit_session_env(session_id: str, env: UploadFile) -> SuccessResponse:
    """Upload environment file for a test session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    # TODO: Store this in a proper storage backend
    sessions[session_id].env = env

    return SuccessResponse(message="Environment file uploaded successfully")


@app.post("/session/{session_id}/tests")
async def submit_tests(session_id: str, request: SubmitTestsRequest) -> SuccessResponse:
    """Add collected tests to a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    unprocessable_tags = set()
    worker_tags = {tag for worker in workers for tag in worker.tags}
    for test in request.tests:
        for tag in test.worker_requirements:
            if tag not in worker_tags:
                unprocessable_tags.add(tag)

        sessions[session_id].tests[test.nodeid] = Session.Test(
            test.worker_requirements, test.nodeid
        )

    if unprocessable_tags:
        # TODO: implement as a validator on the model
        raise fastapi.HTTPException(
            status_code=422,
            detail=f"Tests with unprocessable tags: {unprocessable_tags}",
        )

    return SuccessResponse(message="Tests added successfully")


@app.get("/session/{session_id}/tests")
async def fetch_tests(session_id: str) -> TestsResponse:
    """Get test statuses for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    return TestsResponse(
        statuses={
            test.nodeid: [
                phase
                for phase in test.reports.keys()
                if test.reports[phase] is not None
            ]
            for test in sessions[session_id].tests.values()
        }
    )


@app.post("/worker/session/{session_id}/test")
async def submit_test_report(
    session_id: str, request: SubmitTestReportRequest
) -> SuccessResponse:
    """Upload the result for a test"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if request.nodeid not in sessions[session_id].tests:
        raise fastapi.HTTPException(status_code=404, detail="Test not found")

    test = sessions[session_id].tests[request.nodeid]
    test.reports[request.phase] = request.report
    if request.phase == TestPhase.Teardown:  # TODO
        test.status = TestStatus.Finished

    return SuccessResponse(message="Test result uploaded successfully")


@app.post("/session/{session_id}/test/{phase}")
async def query_test_report(
    session_id: str, phase: TestPhase, request: TestReportRequest
) -> TestReportResponse:
    """Get the report for a test at a particular phase"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if request.nodeid not in sessions[session_id].tests:
        raise fastapi.HTTPException(status_code=404, detail="Test not found")

    test = sessions[session_id].tests[request.nodeid]

    if (report := test.reports[phase]) is None:
        raise fastapi.HTTPException(status_code=404, detail="Test report not found")

    return TestReportResponse(report=report)


@app.get(path="/worker/{worker_id}/session")
async def get_worker_session(worker_id: str) -> SessionResponse | NoSessionResponse:
    """Get the session for a worker"""
    for worker in workers:
        if worker.worker_id == worker_id:
            for session in sessions.values():
                if session.state == SessionState.Running:
                    if any(
                        test.worker_requirements.issubset(worker.tags)
                        for test in session.tests.values()
                    ):
                        return SessionResponse(session_id=session.session_id)

            return NoSessionResponse()

    raise fastapi.HTTPException(status_code=404, detail="Worker not found")


@app.get("/worker/session/{session_id}/env")
async def fetch_worker_session_env(session_id: str):
    """Get the environment for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    return sessions[session_id].env


@app.get("/worker/{worker_id}/session/{session_id}/tests")
async def fetch_session_tests(worker_id: str, session_id: str) -> WorkerActionResponse:
    """Get the tests for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if sessions[session_id].state == SessionState.Setup:
        sessions[session_id].state = SessionState.Running
    elif sessions[session_id].state == SessionState.Stopped:
        return WorkerActionResponse(
            action=WorkerAction.Stop, test_now=None, test_next=None
        )

    for worker in workers:
        if worker.worker_id == worker_id:
            break
    else:
        raise fastapi.HTTPException(status_code=404, detail="Worker not found")

    worker_testable: list[str] = []
    for test in sessions[session_id].tests.values():
        if (
            test.status == TestStatus.Pending
            and test.assigned_worker is None
            and test.worker_requirements.issubset(worker.tags)
        ):
            worker_testable.append(test.nodeid)
            if len(worker_testable) == 1:
                test.assigned_worker = worker
                test.status = TestStatus.Running
            elif len(worker_testable) >= 2:
                break

    return WorkerActionResponse(
        action=WorkerAction.Run if len(worker_testable) > 0 else WorkerAction.Stop,
        test_now=worker_testable[0] if len(worker_testable) > 0 else None,
        test_next=worker_testable[1] if len(worker_testable) > 1 else None,
    )


@app.post("/worker/session/{session_id}/artifacts")
async def upload_artifact(
    session_id: str, request: ArtifactUploadRequest
) -> SuccessResponse:
    """Upload an artifact file from a worker"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    try:
        file_content = base64.b64decode(request.content)
    except Exception as e:
        raise fastapi.HTTPException(
            status_code=400, detail=f"Invalid base64 content: {str(e)}"
        )

    sessions[session_id].artifacts[request.worker_id] = file_content

    return SuccessResponse(message="Artifact uploaded successfully")


@app.get("/session/{session_id}/artifacts")
async def list_artifacts(session_id: str) -> ArtifactListResponse:
    """List all artifacts for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    return ArtifactListResponse(
        artifact_ids=list(sessions[session_id].artifacts.keys())
    )


@app.get("/session/{session_id}/artifacts/{artifact_id}")
async def download_artifact(session_id: str, artifact_id: str) -> StreamingResponse:
    """Download an artifact file"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if artifact_id not in sessions[session_id].artifacts:
        raise fastapi.HTTPException(status_code=404, detail="Artifact not found")

    artifact_content = sessions[session_id].artifacts[artifact_id]

    return StreamingResponse(
        content=artifact_content.decode(), media_type="application/octet-stream"
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
