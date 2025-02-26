import asyncio
import base64
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import Literal, TypedDict, cast

import cloudpickle
import httpx
import pytest
import logging

logger = logging.getLogger(__name__)

httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)

PLUGIN_NAME = "httpdist"


@dataclass
class RunsOn:
    hostname: str | None

    def __init__(self, *args, hostname: str | None = None):
        self.hostname = hostname

    def check(self, node) -> bool:
        # FIXME
        return self.hostname is None or self.hostname == node.gateway.id


NodeId = str
SessionId = str
WorkerId = str


class TestSpec(TypedDict):
    node_id: NodeId
    worker_requirements: list[RunsOn] | None


class TestStatus(StrEnum):
    # FIXME
    Passed = auto()
    Failed = auto()
    Skipped = auto()
    Error = auto()


class Events:
    @dataclass
    class Start:
        hostname: str | None

    @dataclass
    class Finish:
        hostname: str | None

    @dataclass
    class Report:
        hostname: str | None
        nodeid: NodeId
        report: pytest.TestReport


class EndOfSession(Exception):
    pass


class ApiUsageError(Exception):
    pass


class SessionNotStartedError(ApiUsageError):
    pass


class ApiBase:
    # FIXME
    API_URL = "http://localhost:8000"
    session_id: SessionId | None = None

    def __init__(self, config: pytest.Config):
        self.config = config
        self._client = httpx.AsyncClient()

    async def _post(self, path: str, data: dict):
        response = await self._client.post(f"{self.API_URL}/{path}", json=data)
        response.raise_for_status()
        return response.json()

    async def _get(self, path: str, params: dict | None = None):
        response = await self._client.get(f"{self.API_URL}/{path}", params=params)
        response.raise_for_status()
        return response.json()


class ClientApi(ApiBase):
    async def get_client_session(self) -> SessionId:
        session = await self._get("get-session")
        session_id = session["session_id"]
        self.session_id = session_id
        return session_id

    async def submit_tests(self, tests: list[TestSpec]):
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        try:
            await self._post(f"session/{self.session_id}/tests", {"tests": tests})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                raise ApiUsageError(e.response.text)
            raise

    async def fetch_statuses(
        self,
    ) -> dict[NodeId, list[Literal["setup", "call", "teardown"]]]:
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")
        response = await self._get(f"session/{self.session_id}/finished-tests")
        return response["test_status"]

    async def fetch_report(
        self, nodeid: NodeId, phase: Literal["setup", "call", "teardown"]
    ) -> pytest.TestReport:
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        report = await self._post(
            f"session/{self.session_id}/test/report/{phase}", {"node_id": nodeid}
        )
        return cloudpickle.loads(base64.b64decode(report))


class WorkerApi(ApiBase):
    def __init__(self, config: pytest.Config):
        super().__init__(config)
        session_id = config.getoption("httpdist_session_id")
        assert isinstance(session_id, str)
        self.session_id = session_id

    async def signal_ready(self): ...

    async def signal_done(self): ...

    async def fetch_work(self, worker_id: WorkerId) -> tuple[NodeId, NodeId | None]:
        data = await self._get(f"worker/{worker_id}/session/{self.session_id}/tests")

        if data["action"] == "stop":
            raise EndOfSession()

        return data["test_now"], data["test_next"]

    async def report_result(
        self,
        nodeid: NodeId,
        report: pytest.TestReport,
        phase: Literal["setup", "call", "teardown"],
    ):
        data = {
            "node_id": nodeid,
            "report": base64.b64encode(cloudpickle.dumps(report)).decode(),
            "phase": phase,
        }
        await self._post(f"worker/session/{self.session_id}/test/report", data)

    async def upload_artifacts(self): ...


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

        async def _run_tests():
            await self.api_client.signal_ready()

            while True:
                try:
                    nodeid_now, nodeid_next = await self.api_client.fetch_work(
                        self.worker_id
                    )
                    self.process_test(nodeid_now, nodeid_next)
                except EndOfSession:
                    break

            await self.api_client.signal_done()

            await asyncio.gather(*self._reporting_tasks)

        asyncio.run(_run_tests())

        return True

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # This hook is called from within the runtestloop, so we need to run
        # it in a task instead of calling it directly
        self._reporting_tasks.append(
            asyncio.create_task(
                self.api_client.report_result(report.nodeid, report, phase=report.when)
            )
        )

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        asyncio.run(self.api_client.upload_artifacts())


class TestResults:
    nodeids: set[NodeId]
    reports: dict[NodeId, dict[Literal["setup", "call", "teardown"], pytest.TestReport]]

    def __init__(self, nodeids: set[NodeId]):
        self.nodeids = nodeids
        self.reports = {}

    @property
    def all_done(self) -> bool:
        return len(self.reports) == len(self.nodeids) and all(
            "teardown" in phases for phases in self.reports.values()
        )

    def add(self, nodeid: NodeId, report: pytest.TestReport):
        if nodeid not in self.nodeids:
            raise ValueError(f"Unknown nodeid: {nodeid}")

        if report.when not in ["setup", "call", "teardown"]:
            raise ValueError(f"Unknown phase: {report.when}")

        phase = cast(Literal["setup", "call", "teardown"], report.when)

        if (reports := self.reports.get(nodeid)) is not None:
            if phase in reports:
                raise ValueError(f"Test result already set for {nodeid}, phase {phase}")

        self.reports[nodeid] = self.reports.get(nodeid, {}) | {phase: report}  # type: ignore # TODO


class Client:
    """
    Runs on test client.

    - gets test session from server
    - uploads runtime env
    - send collected tests to server
    - receives test results from server
    - downloads artifacts
    """

    runs_on_key = pytest.StashKey[dict[str, list[RunsOn]]]()
    results: TestResults
    statuses: dict[NodeId, list[Literal["setup", "call", "teardown"]]]

    def __init__(self, config: pytest.Config):
        self.config = config
        self.api_client = ClientApi(config)
        self.statuses = {}

    def submit_env(self): ...

    async def submit_tests(self, session: pytest.Session):
        nodeids = {item.nodeid for item in session.items}
        runs_on = session.config.stash[self.runs_on_key]
        await self.api_client.submit_tests(
            [
                TestSpec(node_id=nodeid, worker_requirements=runs_on.get(nodeid))
                for nodeid in nodeids
            ]
        )

    async def fetch_results(self) -> list[pytest.TestReport]:
        new_statuses: dict[
            NodeId, list[Literal["setup", "call", "teardown"]]
        ] = await self.api_client.fetch_statuses()

        new_reports: list[pytest.TestReport] = []
        for nodeid in new_statuses.keys():
            for phase in new_statuses[nodeid]:
                if phase not in self.statuses[nodeid]:
                    new_report = await self.api_client.fetch_report(nodeid, phase)
                    self.results.add(nodeid, new_report)
                    new_reports.append(new_report)

        self.statuses = new_statuses

        return new_reports

    def download_artifacts(self): ...

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        self.download_artifacts()

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection(self, session: pytest.Session):
        session.perform_collect()
        session.config.stash[self.runs_on_key] = {
            item.nodeid: [
                RunsOn(*m.args, **m.kwargs) for m in item.iter_markers(name="runs_on")
            ]
            for item in session.items
        }

        return True

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session: pytest.Session):
        # TODO: shutdown handling

        self.results = TestResults(set(item.nodeid for item in session.items))

        async def run():
            # self.submit_env()  # TODO
            await self.api_client.get_client_session()
            await self.submit_tests(session)

            while True:
                new_reports = await self.fetch_results()
                for report in new_reports:
                    session.config.hook.pytest_runtest_logreport(report=report)

                if self.results.all_done:
                    break

                await asyncio.sleep(1)  # FIXME

        asyncio.run(run())

        return True


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config):
    httpdist_worker_id = config.getoption("httpdist_worker_id")
    httpdist_session_id = config.getoption("httpdist_session_id")

    is_worker = httpdist_worker_id or httpdist_session_id

    if is_worker and not httpdist_worker_id:
        raise pytest.UsageError(
            "httpdist-worker-id is required when running as a worker"
        )

    if is_worker and not httpdist_session_id:
        raise pytest.UsageError(
            "httpdist-session-id is required when running as a worker"
        )

    session = Worker(config) if is_worker else Client(config)
    config.pluginmanager.register(session, PLUGIN_NAME)


@pytest.hookimpl
def pytest_addoption(parser: pytest.Parser, pluginmanager):
    parser.addoption("--httpdist-worker-id", help="Worker ID", default=None)
    parser.addoption("--httpdist-session-id", help="Session ID", default=None)
