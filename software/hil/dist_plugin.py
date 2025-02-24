from dataclasses import dataclass
from pathlib import Path

import pytest

import ray
import ray.util.queue
import socket


@dataclass
class RunsOn:
    hostname: str | None

    def __init__(self, *args, hostname: str | None = None):
        self.hostname = hostname

    def check(self, node) -> bool:
        # FIXME
        return self.hostname is None or self.hostname == node.gateway.id


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

        from _pytest.config import get_config

        # TODO: is this too early? do we need to call pytest_cmdline_parse?
        self.config = get_config(args, None)

        pluginmanager = self.config.pluginmanager
        print("pluginmanager:", pluginmanager)

        self.config.pluginmanager.hook.pytest_cmdline_parse(
            pluginmanager=pluginmanager, args=args
        )

        self.config.option.usepdb = False
        self.config.option.dist = "no"
        self.config.option.distload = False
        self.config.option.numprocesses = None
        self.config.option.maxprocesses = None

        print("config:", self.config)

        # self.config.hook.pytest_cmdline_main(config=self.config)

        print("finished pytest configuration")

        # ls
        print(list(Path.cwd().glob("*")))

    async def process_tests(self):
        # TODO: shutdown signal

        try:
            while True:
                test = await self.test_queue.get_async(block=True)
                print("running test:", test)

                self.message_queue.put(f"{self.hostname}: processing test: {test}")
        except ray.util.queue.Empty:
            pass

    def process_test(self): ...

    @pytest.hookimpl
    def pytest_runtestloop(self, session: pytest.Session):
        print("pytest_runtestloop on remote")


class DSession:
    runs_on_key = pytest.StashKey[dict[str, list[RunsOn]]]()

    def __init__(self, config: pytest.Config):
        if not ray.is_initialized():
            # TODO: from config
            ray.init(
                address="ray://192.168.1.199:10001",
                # namespace="hil",
                runtime_env={
                    # TODO: smarter working dir (relative to __file__, git root, etc)
                    "working_dir": str(Path.cwd()),
                    # TODO: doesn't work — use this instead:
                    # `RAY_RUNTIME_ENV_HOOK=ray._private.runtime_env.uv_runtime_env_hook.hook`
                    # "py_executable": "uv run --isolated",
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

        # TODO: remote per worker for each queue
        self.remote1 = Remote.remote(self.test_queue, self.message_queue, config.args)
        self.remote1.process_tests.remote()  # type: ignore

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

        for item in session.items:
            print("enqueuing:", item.nodeid)
            self.test_queue.put(item.nodeid)

        while True:
            try:
                print("received message:", self.message_queue.get(timeout=1))
            except ray.util.queue.Empty:
                break

        return True


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    session = DSession(config)
    config.pluginmanager.register(session, "dist")
