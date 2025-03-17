import pytest

from .common import PLUGIN_NAME
from .client import Client
from .worker import Worker


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
