import asyncio
import base64
from dataclasses import dataclass
from enum import StrEnum, auto
from io import BytesIO
import itertools
from os import PathLike
import os
from pathlib import Path
from typing import TypedDict
import zipfile

import cloudpickle
import httpx
import pytest
import logging
import tempfile
import shutil

import pathspec

import rich.progress

logger = logging.getLogger(__name__)

httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)

PLUGIN_NAME = "httpdist"
ARTIFACTS_DIR = Path("./artifacts")


class RunsOn(TypedDict):
    tags: list[str]


NodeId = str
SessionId = str
WorkerId = str


class TestPhase(StrEnum):
    Setup = auto()
    Call = auto()
    Teardown = auto()


class TestSpec(TypedDict):
    nodeid: NodeId
    worker_requirements: list[RunsOn] | None


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


class NoWorkersAvailableError(ApiUsageError):
    pass


class ClientApi:
    API_URL = os.getenv("HTTPDIST_API_URL", "http://localhost:8000")
    session_id: SessionId | None = None

    def __init__(self, config: pytest.Config):
        self.config = config

    async def _post(self, path: str, data: dict):
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.API_URL}/{path}", json=data)
            response.raise_for_status()
            return response.json()

    async def _post_files(self, path: str, file_path: PathLike):
        file_path = Path(file_path)
        async with httpx.AsyncClient() as client:
            with open(file_path, "rb") as f:
                response = await client.post(f"{self.API_URL}/{path}", files={"env": f})
            response.raise_for_status()
            return response.json()

    async def _get(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.API_URL}/{path}", params=params)
            response.raise_for_status()
            return response.json()

    async def _get_raw(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.API_URL}/{path}", params=params)
            response.raise_for_status()
            return response

    async def create_session(self, tests: list[TestSpec], env: str):
        try:
            response = await self._post("session/create", {"tests": tests, "env": env})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                raise NoWorkersAvailableError(e.response.json()["detail"])
            raise
        self.session_id = response["session_id"]
        return self.session_id

    async def fetch_statuses(
        self,
    ) -> dict[NodeId, list[TestPhase]]:
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")
        response = await self._get(f"session/{self.session_id}/tests")
        return response["statuses"]

    async def fetch_report(self, nodeid: NodeId, phase: TestPhase) -> pytest.TestReport:
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        response = await self._post(
            f"session/{self.session_id}/test/{phase}", {"nodeid": nodeid}
        )
        report = response["report"]
        return cloudpickle.loads(base64.b64decode(report))

    async def list_artifacts(self) -> dict:
        """List all artifacts available on the server for this session"""
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        response = await self._get(f"session/{self.session_id}/artifacts")
        return response["artifact_ids"]

    async def download_artifact(
        self, artifact_id: str, artifacts_dir: Path = ARTIFACTS_DIR
    ):
        """Download a specific artifact and save it to the given path"""
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        artifacts_dir.parent.mkdir(parents=True, exist_ok=True)

        response = await self._get_raw(
            f"session/{self.session_id}/artifacts/{artifact_id}"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = (Path(temp_dir) / artifact_id).with_suffix(".zip")
            with temp_path.open("wb") as f:
                f.write(response.content)
            shutil.unpack_archive(temp_path, artifacts_dir)
            temp_path.unlink()

        return artifacts_dir


class WorkerApi:
    API_URL = os.getenv("HTTPDIST_API_URL", "http://localhost:8000")
    session_id: SessionId | None = None

    def __init__(self, config: pytest.Config):
        session_id = config.getoption("httpdist_session_id")
        assert isinstance(session_id, str)
        self.session_id = session_id

    def _get(self, path: str, params: dict | None = None):
        with httpx.Client() as client:
            response = client.get(f"{self.API_URL}/{path}", params=params)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, data: dict):
        with httpx.Client() as client:
            response = client.post(f"{self.API_URL}/{path}", json=data)
            response.raise_for_status()
            return response.json()

    def fetch_work(self, worker_id: WorkerId) -> tuple[NodeId, NodeId | None]:
        data = self._get(f"worker/{worker_id}/session/{self.session_id}/tests")

        if data["action"] == "stop":
            raise EndOfSession()

        return data["test_now"], data["test_next"]

    def report_result(
        self,
        worker_id: WorkerId,
        nodeid: NodeId,
        report: pytest.TestReport,
        phase: TestPhase,
    ):
        data = {
            "nodeid": nodeid,
            "report": base64.b64encode(cloudpickle.dumps(report)).decode(),
            "phase": phase,
        }
        self._post(f"worker/{worker_id}/session/{self.session_id}/test", data)

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
            self.worker_id, report.nodeid, report, phase=TestPhase(report.when)
        )

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        self.api_client.upload_artifacts(self.worker_id)


class TestResults:
    nodeids: set[NodeId]
    reports: dict[NodeId, dict[TestPhase, pytest.TestReport]]

    def __init__(self, nodeids: set[NodeId]):
        self.nodeids = nodeids
        self.reports = {}

    @property
    def all_done(self) -> bool:
        return len(self.reports) == len(self.nodeids) and all(
            TestPhase.Teardown in phases for phases in self.reports.values()
        )

    def add(self, nodeid: NodeId, report: pytest.TestReport):
        if nodeid not in self.nodeids:
            raise ValueError(f"Unknown nodeid: {nodeid}")

        try:
            phase = TestPhase(report.when)
        except ValueError:
            raise ValueError(f"Unknown phase: {report.when}")

        if (reports := self.reports.get(nodeid)) is not None:
            if phase in reports:
                raise ValueError(f"Test result already set for {nodeid}, phase {phase}")

        self.reports[nodeid] = self.reports.get(nodeid, {}) | {phase: report}


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
    statuses: dict[NodeId, list[TestPhase]]

    def __init__(self, config: pytest.Config):
        self.config = config
        self.api_client = ClientApi(config)
        self.statuses = {}

    def _zip_env(self, env: Path) -> str:
        """Zip up the environment as a base64 encoded byte-string."""

        # FIXME: this will ignore all but the top-level `.git/hilignore`
        # TODO: this would be way faster if it filtered as it iterated, but
        #   pathspec iters all the files, and then filters things that don't match

        # Create a pathspec to exclude certain files
        # Always ignore .git/ to avoid including the entire repo in the env
        ignore_pattern_lines = [".git/"]
        for ignore_file in itertools.chain(
            env.glob("*.gitignore"), env.glob("*.hilignore")
        ):
            if not ignore_file.is_file():
                continue
            with open(ignore_file, "r") as f:
                ignore_pattern_lines.extend(line.strip() for line in f.readlines())
        ignore_spec = pathspec.GitIgnoreSpec.from_lines(ignore_pattern_lines)
        matched_files = list(ignore_spec.match_tree_files(env, negate=True))

        bytes_io = BytesIO()

        with zipfile.ZipFile(
            bytes_io, "w", compression=zipfile.ZIP_BZIP2, compresslevel=9
        ) as zip_file:
            for file in rich.progress.track(
                matched_files, description="zipping env..."
            ):
                zip_file.write(env / file, file)

            size_mb = bytes_io.tell() / 1024 / 1024
            if size_mb > 5:
                rich.print(
                    f"[yellow]WARNING:[/yellow] Large env size: {size_mb:.1f}MB. "
                    "Consider adding more to [blue].hilignore[/blue]."
                )
                largest_files = sorted(
                    matched_files,
                    key=lambda x: (env / x).stat().st_size,
                    reverse=True,
                )[:10]
                rich.print(
                    f"Largest files: {', '.join(str(file) for file in largest_files)}"
                )

        return base64.b64encode(bytes_io.getvalue()).decode()

    async def create_session(self, session: pytest.Session):
        nodeids = {item.nodeid for item in session.items}
        runs_on = session.config.stash[self.runs_on_key]
        test = [
            TestSpec(nodeid=nodeid, worker_requirements=runs_on.get(nodeid))
            for nodeid in nodeids
        ]
        env_zip = self._zip_env(session.config.rootpath)
        await self.api_client.create_session(test, env_zip)

    async def fetch_results(self) -> list[pytest.TestReport]:
        new_statuses: dict[
            NodeId, list[TestPhase]
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

    async def download_artifacts(self):
        """Download artifact files produced by workers"""

        artifact_ids = await self.api_client.list_artifacts()
        if not artifact_ids:
            return

        ARTIFACTS_DIR.mkdir(exist_ok=True)

        tasks = [
            self.api_client.download_artifact(artifact_id)
            for artifact_id in artifact_ids
        ]

        await asyncio.gather(*tasks)

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        if exitstatus == pytest.ExitCode.OK:
            asyncio.run(self.download_artifacts())

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
            await self.create_session(session)

            while True:
                new_reports = await self.fetch_results()
                for report in new_reports:
                    session.config.hook.pytest_runtest_logreport(report=report)

                if self.results.all_done:
                    break

                # Loop delay to avoid overwhelming server
                await asyncio.sleep(1)

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
