import logging
import uuid
from dataclasses import dataclass, field
from typing import Literal

import fastapi
import uvicorn
from fastapi import UploadFile
from pydantic import BaseModel

from httpdist_server.models import (
    GetSessionTestsResponse,
    GetWorkerSessionTestsResponse,
    PostSessionsTestsRequest,
    PostWorkerSessionTestReportRequest,
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
        node_id: str

        status: Literal["pending", "running", "finished"] = "pending"
        assigned_worker: Worker | None = None
        report: str | None = None

    session_id: str

    state: Literal["setup", "running", "stopped"] = "setup"
    tests: dict[str, Test] = field(default_factory=dict)
    env: UploadFile | None = None

    async def stop(self):
        self.state = "stopped"
        if self.env is not None:
            await self.env.close()


# TODO: stick this in a database or something
sessions: dict[str, Session] = {
    "test-session": Session(
        session_id="test-session",
        tests={
            "tests/test_nothing.py::test_nothing": Session.Test(
                node_id="tests/test_nothing.py::test_nothing",
                worker_requirements={"cellsim"},
            ),
            "tests/test_nothing.py::test_fail": Session.Test(
                node_id="tests/test_nothing.py::test_fail",
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


class GetSessionResponse(BaseModel):
    """Response to a request to start a new session"""

    session_id: str


@app.get("/get-session")
async def start_session():
    session_id = str(uuid.uuid4())
    sessions[session_id] = Session(session_id=session_id)
    return GetSessionResponse(session_id=session_id)


@app.post("/session/{session_id}/stop")
async def stop_session(session_id: str):
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    await sessions[session_id].stop()

    return {"message": "Stop signal sent"}


@app.post("/session/{session_id}/env")
async def upload_session_env(session_id: str, env: UploadFile):
    """Upload environment file for a test session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    # TODO: Store this in a proper storage backend
    sessions[session_id].env = env

    return {"message": "Environment file uploaded successfully"}


@app.post("/session/{session_id}/tests")
async def add_tests(session_id: str, request: PostSessionsTestsRequest):
    """Add a test to a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    unprocessable_tags = set()
    worker_tags = {tag for worker in workers for tag in worker.tags}
    for test in request.tests:
        for tag in test.worker_requirements:
            if tag not in worker_tags:
                unprocessable_tags.add(tag)

        sessions[session_id].tests[test.node_id] = Session.Test(
            test.worker_requirements, test.node_id
        )

    if unprocessable_tags:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f"Tests with unprocessable tags: {unprocessable_tags}",
        )

    return {"message": "Tests added successfully"}


@app.get("/session/{session_id}/finished-tests")
async def get_finished_tests(session_id: str) -> GetSessionTestsResponse:
    """Get the tests for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    return GetSessionTestsResponse(
        test_status={
            test.node_id: test.status
            for test in sessions[session_id].tests.values()
            if test.status == "finished"
        }
    )


@app.post("/worker/session/{session_id}/test/report")
async def post_test_report(
    session_id: str, request: PostWorkerSessionTestReportRequest
):
    """Upload the result for a test"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if request.node_id not in sessions[session_id].tests:
        raise fastapi.HTTPException(status_code=404, detail="Test not found")

    test = sessions[session_id].tests[request.node_id]
    test.report = request.report
    test.status = "finished"

    return {"message": "Test result uploaded successfully"}


@app.get("/session/{session_id}/test/{test_id}/report")
async def get_test_report(session_id: str, test_id: str) -> str:
    """Get the report for a test"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if test_id not in sessions[session_id].tests:
        raise fastapi.HTTPException(status_code=404, detail="Test not found")

    test = sessions[session_id].tests[test_id]
    if test.report is None:
        raise fastapi.HTTPException(status_code=404, detail="Test report not found")

    return test.report


@app.get("/worker/{worker_id}/get-session")
async def get_session(worker_id: str) -> str | None:
    """Get the session for a worker"""
    for worker in workers:
        if worker.worker_id == worker_id:
            for session in sessions.values():
                if session.state == "running":
                    if any(
                        test.worker_requirements.issubset(worker.tags)
                        for test in session.tests.values()
                    ):
                        return session.session_id

            return None

    raise fastapi.HTTPException(status_code=404, detail="Worker not found")


@app.get("/worker/session/{session_id}/env")
async def get_session_env(session_id: str):
    """Get the environment for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    return sessions[session_id].env


@app.get("/worker/{worker_id}/session/{session_id}/tests")
async def get_session_tests(worker_id: str, session_id: str):
    """Get the tests for a session"""
    if session_id not in sessions:
        raise fastapi.HTTPException(status_code=404, detail="Session not found")

    if sessions[session_id].state == "setup":
        sessions[session_id].state = "running"
    elif sessions[session_id].state == "stopped":
        return GetWorkerSessionTestsResponse(
            action="stop",
            test_now=None,
            test_next=None,
        )

    for worker in workers:
        if worker.worker_id == worker_id:
            break
    else:
        raise fastapi.HTTPException(status_code=404, detail="Worker not found")

    worker_testable: list[str] = []
    for test in sessions[session_id].tests.values():
        if (
            test.status == "pending"
            and test.assigned_worker is None
            and test.worker_requirements.issubset(worker.tags)
        ):
            worker_testable.append(test.node_id)
            test.assigned_worker = worker
            test.status = "running"

        if len(worker_testable) >= 2:
            break

    return GetWorkerSessionTestsResponse(
        action="run" if len(worker_testable) > 0 else "stop",
        test_now=worker_testable[0] if len(worker_testable) > 0 else None,
        test_next=worker_testable[1] if len(worker_testable) > 1 else None,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
