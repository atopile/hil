import asyncio
import base64
import itertools
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import cloudpickle
import httpx
import pathspec
import pytest
import rich.progress

from .common import (
    ARTIFACTS_DIR,
    BaseApi,
    NodeId,
    NoWorkersAvailableError,
    RunsOn,
    SessionId,
    SessionNotStartedError,
    TestPhase,
    TestSpec,
)

logger = logging.getLogger(__name__)


class RemoteTest:
    def __init__(self, nodeid: NodeId, worker_requirements: list[RunsOn]):
        self.nodeid = nodeid
        self.reports: dict[TestPhase, pytest.TestReport] = {}
        self.worker_requirements: list[RunsOn] = worker_requirements

    @property
    def done(self) -> bool:
        return TestPhase.Teardown in self.reports

    def add_report(self, report: pytest.TestReport):
        try:
            phase = TestPhase(report.when)
        except ValueError:
            raise ValueError(f"Unknown phase: {report.when}")

        if phase in self.reports:
            raise ValueError(
                f"Test result already set for {self.nodeid}, phase {phase}"
            )

        self.reports[phase] = report

    def get_test_spec(self) -> TestSpec:
        return TestSpec(
            nodeid=self.nodeid, worker_requirements=self.worker_requirements
        )


class ClientApi(BaseApi):
    API_URL = os.getenv("HTTPDIST_API_URL", "http://localhost:8000")
    session_id: SessionId | None = None

    def __init__(self, config: pytest.Config):
        self.config = config

    def get_client_session(self) -> SessionId:
        session = self._get("session")
        session_id = session["session_id"]
        self.session_id = session_id
        return session_id

    def submit_env(self, env: Path):
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        self._post_file(
            f"session/{self.session_id}/env",
            env,
        )

    def submit_tests(self, tests: list[TestSpec]):
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        try:
            self._post(f"session/{self.session_id}/tests", {"tests": tests})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                raise NoWorkersAvailableError(e.response.json()["detail"])
            raise

    async def fetch_statuses(
        self,
    ) -> dict[NodeId, list[TestPhase]]:
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")
        response = await self._aget(f"session/{self.session_id}/tests")
        return response["statuses"]

    async def fetch_report(self, nodeid: NodeId, phase: TestPhase) -> pytest.TestReport:
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        response = await self._apost(
            f"session/{self.session_id}/test/{phase}", {"nodeid": nodeid}
        )
        report = response["report"]
        return cloudpickle.loads(base64.b64decode(report))

    async def list_artifacts(self) -> dict:
        """List all artifacts available on the server for this session"""
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        response = await self._aget(f"session/{self.session_id}/artifacts")
        return response["artifact_ids"]

    async def download_artifact(
        self, artifact_id: str, artifacts_dir: Path = ARTIFACTS_DIR
    ):
        """Download a specific artifact and save it to the given path"""
        if self.session_id is None:
            raise SessionNotStartedError("Must have an active session")

        artifacts_dir.parent.mkdir(parents=True, exist_ok=True)

        response = await self._aget_raw(
            f"session/{self.session_id}/artifacts/{artifact_id}"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = (Path(temp_dir) / artifact_id).with_suffix(".zip")
            with temp_path.open("wb") as f:
                f.write(response.content)
            shutil.unpack_archive(temp_path, artifacts_dir)
            temp_path.unlink()

        return artifacts_dir


class Client:
    """
    Runs on test client.

    - gets test session from server
    - uploads runtime env
    - send collected tests to server
    - receives test results from server
    - downloads artifacts
    """

    def __init__(self, config: pytest.Config):
        self.config = config
        self.api_client = ClientApi(config)
        self.remote_tests: dict[NodeId, RemoteTest] = {}

    def submit_env(self, env: Path):
        # Create a pathspec to exclude certain files
        # FIXME: this will ignore all but the top-level `.git/hilignore`
        # Always ignore .git/ to avoid including the entire repo in the env
        # FIXME: this would be way faster if it filtered as it iterated, but
        # pathspec iters all the files, and then filters things that don't match
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

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "env.zip"
            with zipfile.ZipFile(zip_path, "w") as zip_file:
                for file in rich.progress.track(
                    matched_files, description="zipping env..."
                ):
                    zip_file.write(env / file, file)

            size_mb = zip_path.stat().st_size / 1024 / 1024
            if size_mb > 5:
                rich.print(
                    f"[yellow]WARNING:[/yellow] Large env size: {size_mb:.1f}MB. Consider adding more to [blue].hilignore[/blue]."
                )
                largest_files = sorted(
                    matched_files,
                    key=lambda x: (env / x).stat().st_size,
                    reverse=True,
                )[:10]
                rich.print(
                    f"Largest files: {', '.join(str(file) for file in largest_files)}"
                )

            self.api_client.submit_env(zip_path)

    async def fetch_new_reports(self) -> list[pytest.TestReport]:
        new_reports: list[pytest.TestReport] = []
        fetch_tasks: list[asyncio.Task] = []
        for nodeid, finished_phases in (await self.api_client.fetch_statuses()).items():
            newly_finished_phases = (
                self.remote_tests[nodeid].reports.keys() - finished_phases
            )
            for phase in newly_finished_phases:

                async def _fetch_report():
                    new_report = await self.api_client.fetch_report(nodeid, phase)
                    self.remote_tests[nodeid].add_report(new_report)
                    new_reports.append(new_report)

                fetch_tasks.append(asyncio.create_task(_fetch_report()))

        await asyncio.gather(*fetch_tasks)

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
        for item in session.items:
            worker_requirements = [
                RunsOn(*m.args, **m.kwargs) for m in item.iter_markers(name="runs_on")
            ]
            if worker_requirements:
                self.remote_tests[item.nodeid] = RemoteTest(
                    item.nodeid, worker_requirements
                )

        return True

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session: pytest.Session):
        # TODO: shutdown handling

        def _raise_stops():
            if session.shouldfail:
                raise session.Failed(session.shouldfail)
            if session.shouldstop:
                raise session.Interrupted(session.shouldstop)

        # This sections is largely copied from pytest._pytest.main's
        # pytest_runtestloop adding filtering for remote tests
        if (
            session.testsfailed
            and not session.config.option.continue_on_collection_errors
        ):
            raise session.Interrupted(
                "%d error%s during collection"
                % (session.testsfailed, "s" if session.testsfailed != 1 else "")
            )

        if session.config.option.collectonly:
            return True

        # First, setup the remote meaning workers can be allocated, provisioned and start processing
        # God... Sam, I see what you meant about the go-routines now. Refactoring this was a PITA
        if self.remote_tests:
            self.api_client.get_client_session()
            self.submit_env(session.config.rootpath)

            # Submit remote tests to the server
            remote_test_specs = [
                remote_test.get_test_spec()
                for remote_test in self.remote_tests.values()
            ]
            self.api_client.submit_tests(remote_test_specs)

        # Then, kick-off locally run tests, polling the remote for finished tests as we go
        local_items = [i for i in session.items if i.nodeid not in self.remote_tests]
        for i, item in enumerate(local_items):
            nextitem = local_items[i + 1] if i + 1 < len(local_items) else None
            item.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)

            if self.remote_tests and not all(
                test.done for test in self.remote_tests.values()
            ):
                for report in asyncio.run(self.fetch_new_reports()):
                    session.config.hook.pytest_runtest_logreport(report=report)

            _raise_stops()

        # Finally, having exhausted our local tests, ensure we also exhaust all remote tests too
        if self.remote_tests:

            async def _monitor_remote_tests():
                while True:
                    new_reports = await self.fetch_new_reports()
                    for report in new_reports:
                        session.config.hook.pytest_runtest_logreport(report=report)

                    # Break once all remote tests are complete
                    if all(test.done for test in self.remote_tests.values()):
                        break

                    # Loop delay to avoid overwhelming server
                    await asyncio.sleep(1)
                    _raise_stops()

            asyncio.run(_monitor_remote_tests())

        return True
