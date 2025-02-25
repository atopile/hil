from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import pytest

import ray
import ray.util.queue
import socket


from _pytest.config import _prepareconfig


@dataclass
class RunsOn:
    hostname: str | None

    def __init__(self, *args, hostname: str | None = None):
        self.hostname = hostname

    def check(self, node) -> bool:
        # FIXME
        return self.hostname is None or self.hostname == node.gateway.id


class Event(TypedDict):
    event: str
    nodeid: str
    hostname: str | None
    item: object | None


# TODO: actor pool
@ray.remote(resources={"remote": 1})
class Remote:
    """
    Runs on remote node.

    Sets up pytest test loop. Receives test nodes to run.
    """

    def __init__(
        self,
        test_queue: ray.util.queue.Queue,
        message_queue: ray.util.queue.Queue,
        args: list[str],
    ):
        self.test_queue = test_queue
        self.message_queue = message_queue
        self.hostname = socket.gethostname()
        self.config = _prepareconfig(args, [self])

        # TODO: review
        # self.config.option.loadgroup = self.config.getvalue("dist") == "loadgroup"
        self.config.option.looponfail = False
        self.config.option.usepdb = False
        self.config.option.dist = "no"
        self.config.option.distload = False
        self.config.option.numprocesses = None
        self.config.option.maxprocesses = None
        self.config.option.basetemp = Path.cwd() / "dist_tmp"

        # TODO: suppress terminal output
        self.config.hook.pytest_cmdline_main(config=self.config)

    def get_item(self, nodeid: str):
        # TODO: build index

        for item in self.session.items:
            if item.nodeid == nodeid:
                return item

        raise ValueError(f"Item with nodeid {nodeid} not found")

    def process_test(self, nodeid_now: str, nodeid_next: str | None):
        print("processing: ", [nodeid_now, nodeid_next])
        item_now = self.get_item(nodeid_now)
        item_next = self.get_item(nodeid_next) if nodeid_next else None

        self.config.hook.pytest_runtest_protocol(item=item_now, nextitem=item_next)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session: pytest.Session):
        self.session = session

        # TODO: shutdown signal

        try:
            test_now = self.test_queue.get(block=True, timeout=1)

            while True:
                try:
                    test_next = self.test_queue.get(block=True, timeout=1)
                except ray.util.queue.Empty:
                    # TODO: 'finished' event
                    test_next = None

                self.process_test(test_now, test_next)

                if test_next is None:
                    break

                test_now = test_next
        except ray.util.queue.Empty:
            # TODO: 'finished' event
            return True

        return True

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # TODO: typed message
        self.message_queue.put(
            {
                "event": "report",
                "nodeid": report.nodeid,
                "hostname": self.hostname,
                "report": report,
            }
        )


class DSession:
    runs_on_key = pytest.StashKey[dict[str, list[RunsOn]]]()

    def __init__(self, config: pytest.Config):
        if not ray.is_initialized():
            # TODO: from config
            ray.init(
                log_to_driver=False,  # hide worker output
                address="ray://192.168.1.199:10001",
                # namespace="hil",
                runtime_env={
                    # `export RAY_RUNTIME_ENV_HOOK=ray._private.runtime_env.uv_runtime_env_hook.hook`
                    # TODO: exclusions from file?
                    "excludes": [
                        "**/*.step",
                        "**/*.wrl",
                        "**/*.kicad_pcb",
                        "**/*.kicad_pro",
                        "**/*.kicad_sch",
                        "**/fp-lib-table",
                    ],
                },
            )

        # TODO: queue per resource type
        self.test_queue = ray.util.queue.Queue()
        self.message_queue = ray.util.queue.Queue()

        args = [str(x) for x in config.invocation_params.args or ()]

        # TODO: remote per worker for each queue
        self.remote1 = Remote.remote(self.test_queue, self.message_queue, args)

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

        reports_by_nodeid = {item.nodeid: None for item in session.items}

        # TODO: manage queue size
        self.test_queue.put_nowait_batch([item.nodeid for item in session.items])

        # TODO: start/finish events
        while True:
            try:
                message = self.message_queue.get(block=True, timeout=0.1)
                reports_by_nodeid[message["nodeid"]] = message["report"]
                session.config.hook.pytest_runtest_logreport(report=message["report"])
            except ray.util.queue.Empty:
                # TODO: what if results aren't coming?
                if all(reports_by_nodeid.values()):
                    break

        # TODO: better error
        assert all(reports_by_nodeid.values()), "No test report for: " + ", ".join(
            [nodeid for nodeid, report in reports_by_nodeid.items() if report is None]
        )

        return True


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    session = DSession(config)
    config.pluginmanager.register(session, "dist")
