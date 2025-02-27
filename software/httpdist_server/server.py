from datetime import datetime, timedelta
import logging
import base64
from dataclasses import dataclass, field
import os
from pathlib import Path
import uuid

import fastapi
from hil.utils.pet_name import get_pet_name
import uvicorn
from fastapi import BackgroundTasks, Response, UploadFile
from supabase import create_client

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
    WorkerInfoResponse,
    WorkerUpdateRequest,
)

logger = logging.getLogger(__name__)

app = fastapi.FastAPI()

ENV_DIR = Path(".envs")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ynesgbuoxmszjrkzazxz.supabase.co")
SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InluZXNnYnVveG1zempya3phenh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzQzNzg5NDYsImV4cCI6MjA0OTk1NDk0Nn0.6KxEoSHTgyV4jKnnLAG5-Y9tWfHOzpl0qnA_NPzGUBo",
)
WORKER_TIMEOUT = timedelta(minutes=2)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


@dataclass
class ConfiguredWorker:
    worker_id: str  # Typically the worker's mac address
    pet_name: str
    tags: set[str]
    last_seen: datetime


@dataclass
class Session:
    @dataclass
    class Test:
        worker_requirements: set[str]
        nodeid: NodeId

        status: TestStatus = TestStatus.Pending
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
    env: Path | None = None
    artifacts: dict[str, bytes] = field(default_factory=dict)

    def stop(self):
        self.state = SessionState.Stopped
        if self.env is not None:
            self.env.unlink()


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


class WorkerNotFound(fastapi.HTTPException):
    def __init__(self, worker_id: str):
        super().__init__(status_code=404, detail=f"Worker {worker_id} not found")


class WorkerUnconfigured(fastapi.HTTPException):
    def __init__(self, worker_id: str):
        super().__init__(status_code=422, detail=f"Worker {worker_id} is unconfigured")


async def _get_worker(worker_id: str) -> ConfiguredWorker:
    workers_response = (
        supabase.table("workers").select("*").eq("worker_id", worker_id).execute()
    )
    if len(workers_response.data) == 0:
        raise WorkerNotFound(worker_id)

    tags = workers_response.data[0]["tags"]
    if tags is None:
        raise WorkerUnconfigured(worker_id)

    pet_name = workers_response.data[0]["pet_name"]
    if pet_name is None:
        pet_name = get_pet_name(worker_id)

    return ConfiguredWorker(
        worker_id=workers_response.data[0]["worker_id"],
        pet_name=pet_name,
        tags=tags,
        last_seen=datetime.fromisoformat(workers_response.data[0]["last_seen"]),
    )


async def _get_active_workers() -> list[ConfiguredWorker]:
    workers = []
    workers_response = (
        supabase.table("workers")
        .select("*")
        .gte("last_seen", datetime.now() - WORKER_TIMEOUT)
        .neq("tags", None)
        .execute()
    )
    for worker in workers_response.data:
        workers.append(
            ConfiguredWorker(
                worker_id=worker["worker_id"],
                pet_name=worker["pet_name"],
                tags=worker["tags"],
                last_seen=datetime.fromisoformat(worker["last_seen"]),
            )
        )
    return workers


async def _worker_seen(worker_id: str):
    supabase.table("workers").update({"last_seen": datetime.now().isoformat()}).eq(
        "worker_id", worker_id
    ).execute()


@app.get("/")
async def root():
    return {"message": "Hello, World!"}


@app.get("/session")
async def start_session() -> SessionResponse:
    session_id = str(uuid.uuid4())
    sessions[session_id] = Session(session_id=session_id)
    return SessionResponse(session_id=session_id)


@app.post("/session/{session_id}/stop")
async def stop_session(session_id: str) -> SuccessResponse:
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    sessions[session_id].stop()

    return SuccessResponse(message="Stop signal sent")


@app.post("/session/{session_id}/env")
async def submit_session_env(session_id: str, env: UploadFile) -> SuccessResponse:
    """Upload environment file for a test session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    # TODO: Store this in a proper storage backend
    env_path = ENV_DIR / session_id
    env_path.parent.mkdir(parents=True, exist_ok=True)
    with env_path.open("wb") as f:
        f.write(await env.read())

    sessions[session_id].env = env_path
    logger.info(f"Uploaded environment file for session {session_id}")

    return SuccessResponse(message="Environment file uploaded successfully")


@app.post("/session/{session_id}/tests")
async def submit_tests(session_id: str, request: SubmitTestsRequest) -> SuccessResponse:
    """Add collected tests to a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    workers = await _get_active_workers()

    if not workers:
        raise fastapi.HTTPException(status_code=503, detail="No workers available")

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
            status_code=503,
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
async def get_worker_session(
    worker_id: str, background_tasks: BackgroundTasks
) -> SessionResponse | NoSessionResponse:
    """Get the session for a worker, or if the worker isn't registered, register it."""
    worker_exists = bool(
        supabase.table("workers").select("*").eq("worker_id", worker_id).execute().data
    )

    if worker_exists:
        await _worker_seen(worker_id)

    else:
        pet_name = get_pet_name(worker_id)
        supabase.table("workers").insert(
            {
                "worker_id": worker_id,
                "pet_name": pet_name,
                "last_seen": datetime.now().isoformat(),
            }
        ).execute()

    worker = await _get_worker(worker_id)

    for session in sessions.values():
        if session.state == SessionState.Running:
            if any(
                test.worker_requirements.issubset(worker.tags)
                for test in session.tests.values()
            ):
                return SessionResponse(session_id=session.session_id)

    return NoSessionResponse()


@app.get("/worker/session/{session_id}/env")
async def fetch_worker_session_env(session_id: str) -> Response:
    """Get the environment for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    session = sessions[session_id]

    if session.env is None:
        raise fastapi.HTTPException(
            status_code=404, detail="Environment file not found"
        )

    file_content = session.env.read_bytes()

    return Response(
        content=file_content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="env.zip"'},
    )


@app.get("/worker/{worker_id}/session/{session_id}/tests")
async def fetch_session_tests(
    worker_id: str, session_id: str, background_tasks: BackgroundTasks
) -> WorkerActionResponse:
    """Get the tests for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if sessions[session_id].state == SessionState.Setup:
        sessions[session_id].state = SessionState.Running
    elif sessions[session_id].state == SessionState.Stopped:
        return WorkerActionResponse(
            action=WorkerAction.Stop, test_now=None, test_next=None
        )

    background_tasks.add_task(_worker_seen, worker_id)
    worker = await _get_worker(worker_id)
    worker_testable: list[str] = []
    for test in sessions[session_id].tests.values():
        if test.status == TestStatus.Pending and test.worker_requirements.issubset(
            worker.tags
        ):
            worker_testable.append(test.nodeid)
            if len(worker_testable) == 1:
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
async def download_artifact(session_id: str, artifact_id: str) -> Response:
    """Download an artifact file"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if artifact_id not in sessions[session_id].artifacts:
        raise fastapi.HTTPException(status_code=404, detail="Artifact not found")

    artifact_content = sessions[session_id].artifacts[artifact_id]

    return Response(content=artifact_content, media_type="application/octet-stream")


@app.post("/worker/{worker_id}/update")
async def update_worker(
    worker_id: str, request: WorkerUpdateRequest
) -> SuccessResponse:
    """Update a worker's information"""
    if (
        not supabase.table("workers")
        .select("*")
        .eq("worker_id", worker_id)
        .execute()
        .data
    ):
        raise fastapi.HTTPException(status_code=404, detail="Worker not found")

    supabase.table("workers").update(
        {"pet_name": request.pet_name, "tags": request.tags}
    ).eq("worker_id", worker_id).execute()
    return SuccessResponse(message="Worker updated successfully")


@app.post("/worker/{worker_id}/heartbeat")
async def worker_heartbeat(worker_id: str) -> SuccessResponse:
    """Update a worker's information"""
    await _worker_seen(worker_id)
    return SuccessResponse(message="Heartbeat received")


@app.get("/worker/{worker_id}/info")
async def get_worker_info(worker_id: str) -> WorkerInfoResponse:
    """Get information about a worker"""
    worker = await _get_worker(worker_id)
    return WorkerInfoResponse(
        worker_id=worker.worker_id,
        pet_name=worker.pet_name,
        tags=list(worker.tags),
    )


@app.get("/worker/list")
async def list_workers() -> list[WorkerInfoResponse]:
    """List all workers"""
    workers = await _get_active_workers()
    return [
        WorkerInfoResponse(
            worker_id=worker.worker_id,
            pet_name=worker.pet_name,
            tags=list(worker.tags),
        )
        for worker in workers
    ]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
