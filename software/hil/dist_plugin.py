from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
import time

import httpx
import pytest


PLUGIN_NAME = "dist"


@dataclass
class RunsOn:
    hostname: str | None

    def __init__(self, *args, hostname: str | None = None):
        self.hostname = hostname

    def check(self, node) -> bool:
        # FIXME
        return self.hostname is None or self.hostname == node.gateway.id


NodeId = str


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


class ApiClient:
    # FIXME
    API_URL = "http://localhost:8000"

    def __init__(self, config: pytest.Config):
        self.config = config
        self._client = httpx.AsyncClient()


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
        self.api_client = ApiClient(config)

        # TODO: review
        # self.config.option.loadgroup = self.config.getvalue("dist") == "loadgroup"
        self.config.option.looponfail = False
        self.config.option.usepdb = False
        self.config.option.dist = "no"
        self.config.option.distload = False
        self.config.option.numprocesses = None
        self.config.option.maxprocesses = None
        self.config.option.basetemp = Path.cwd() / "dist_tmp"

    def process_test(self, nodeid_now: str, nodeid_next: str | None):
        item_now = self._items_by_nodeid[nodeid_now]
        item_next = self._items_by_nodeid[nodeid_next] if nodeid_next else None
        self.config.hook.pytest_runtest_protocol(item=item_now, nextitem=item_next)

    def signal_ready(self): ...

    def signal_done(self): ...

    def fetch_work(self) -> tuple[NodeId, NodeId | None]: ...

    def report_result(self, nodeid: NodeId, report: pytest.TestReport): ...

    def upload_artifacts(self): ...

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session: pytest.Session):
        self.session = session
        self._items_by_nodeid = {item.nodeid: item for item in session.items}

        self.signal_ready()

        while True:
            try:
                nodeid_now, nodeid_next = self.fetch_work()
                self.process_test(nodeid_now, nodeid_next)
            except EndOfSession:
                break

        self.signal_done()

        return True

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.report_result(report.nodeid, report)

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        self.upload_artifacts()


class TestResults:
    nodeids: set[NodeId]
    reports: dict[NodeId, pytest.TestReport]

    def __init__(self, nodeids: set[NodeId]):
        self.nodeids = nodeids
        self.reports = {}

    @property
    def all_done(self) -> bool:
        return len(self.reports) == len(self.nodeids)

    def add(self, nodeid: NodeId, report: pytest.TestReport):
        if nodeid not in self.nodeids:
            raise ValueError(f"Unknown nodeid: {nodeid}")

        if self.reports[nodeid] is not None:
            raise ValueError(f"Test result already set for {nodeid}")

        self.reports[nodeid] = report


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
    statuses: dict[NodeId, TestStatus]

    def __init__(self, config: pytest.Config):
        self.config = config
        self.api_client = ApiClient(config)

    def submit_env(self): ...

    def submit_tests(self, session: pytest.Session): ...

    def fetch_results(self) -> list[pytest.TestReport]:
        # TOOD: fetch new statuses
        new_statuses: dict[NodeId, TestStatus] = {}
        new_reports: list[pytest.TestReport] = []

        for nodeid in new_statuses.keys() - self.statuses.keys():
            new_report = self.fetch_report(nodeid)
            self.results.add(nodeid, new_report)
            new_reports.append(new_report)

        self.statuses = new_statuses

        return new_reports

    def fetch_report(self, nodeid: NodeId) -> pytest.TestReport: ...

    def download_artifacts(self): ...

    @pytest.hookimpl
    def pytest_sessionstart(self, session: pytest.Session):
        # TODO: get session
        self.submit_env()

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

        self.submit_tests(session)

        self.results = TestResults(set(item.nodeid for item in session.items))

        while True:
            new_reports = self.fetch_results()
            for report in new_reports:
                session.config.hook.pytest_runtest_logreport(report=report)

            if self.results.all_done:
                break

            time.sleep(1)  # FIXME

        return True


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    is_worker = config.getoption("worker")
    session = Worker(config) if is_worker else Client(config)
    config.pluginmanager.register(session, PLUGIN_NAME)


@pytest.hookimpl
def pytest_addoption(parser, pluginmanager):
    parser.addoption("--worker", help="Run as a worker node", default=False)
