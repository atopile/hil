import asyncio
import base64
from pathlib import Path

import cloudpickle
import pytest
import logging
import tempfile
import shutil

from .common import BaseApi, WorkerId, NodeId, EndOfSession, TestPhase, ARTIFACTS_DIR

logger = logging.getLogger(__name__)


class WorkerApi(BaseApi):
    def __init__(self, config: pytest.Config):
        super().__init__(config)

        session_id = config.getoption("httpdist_session_id")
        assert isinstance(session_id, str)
        self.session_id = session_id

    def fetch_work(self, worker_id: WorkerId) -> tuple[NodeId, NodeId | None]:
        data = self._get(f"worker/{worker_id}/session/{self.session_id}/tests")

        if data["action"] == "stop":
            raise EndOfSession()

        return data["test_now"], data["test_next"]

    def report_result(
        self, nodeid: NodeId, report: pytest.TestReport, phase: TestPhase
    ):
        data = {
            "nodeid": nodeid,
            "report": base64.b64encode(cloudpickle.dumps(report)).decode(),
            "phase": phase,
        }
        self._post(f"worker/session/{self.session_id}/test", data)

    def upload_artifacts(self, worker_id: str):
        """Upload all artifact files"""
        if not ARTIFACTS_DIR.exists():
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / f"{worker_id}.zip"
            try:
                shutil.make_archive(
                    str(zip_path.with_suffix("")),
                    "zip",
                    root_dir=ARTIFACTS_DIR,
                    base_dir=".",
                )

                with open(zip_path, "rb") as zip_file:
                    self._post(
                        f"worker/session/{self.session_id}/artifacts",
                        {
                            "worker_id": worker_id,
                            "content": base64.b64encode(zip_file.read()).decode(),
                        },
                    )

            finally:
                zip_path.unlink()


class Worker:
    """
    Runs on worker node once test session is started.

    - retrieves active test session from server
    - polls for allocated tests
    - executes tests and reports results
    - uploads artifacts at end of session
    """

    def __init__(self, config: pytest.Config):
        self.config = config
        self.api_client = WorkerApi(config)
        self._reporting_tasks: list[asyncio.Task] = []

        # TODO: review
        # self.config.option.loadgroup = self.config.getvalue("dist") == "loadgroup"
        self.config.option.looponfail = False
        self.config.option.usepdb = False
        self.config.option.dist = "no"
        self.config.option.distload = False
        self.config.option.numprocesses = None
        self.config.option.maxprocesses = None
        self.config.option.basetemp = Path.cwd() / "dist_tmp"

    @property
    def worker_id(self) -> str:
        worker_id = self.config.getoption("httpdist_worker_id")
        assert isinstance(worker_id, str)
        return worker_id

    def process_test(self, nodeid_now: str, nodeid_next: str | None):
        item_now = self._items_by_nodeid[nodeid_now]
        item_next = self._items_by_nodeid[nodeid_next] if nodeid_next else None
        self.config.hook.pytest_runtest_protocol(item=item_now, nextitem=item_next)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session: pytest.Session):
        self.session = session
        self._items_by_nodeid = {item.nodeid: item for item in session.items}

        while True:
            try:
                nodeid_now, nodeid_next = self.api_client.fetch_work(self.worker_id)
                self.process_test(nodeid_now, nodeid_next)
            except EndOfSession:
                break

        return True

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # This hook is called from within the runtestloop, so we need to run
        # it in a task instead of calling it directly
        self.api_client.report_result(
            report.nodeid, report, phase=TestPhase(report.when)
        )

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        self.api_client.upload_artifacts(self.worker_id)
