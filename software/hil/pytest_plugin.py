"""
Pytest plugin providing a 'record' fixture for capturing data traces in tests, then
generating interactive Altair plots. The plots are automatically attached to the pytest-html
report for easy inspection of test-generated data.

This plugin leverages:
    - pytest-html for HTML report customization
    - Altair for interactive chart generation
    - Polars for efficient DataFrame handling

References:
    - https://pytest-html.readthedocs.io/en/latest/api_reference.html
    - https://altair-viz.github.io/
    - The 'record' class is from hil.framework in this same package.
"""

import logging
import socket
from datetime import datetime
from pathlib import Path
from typing import Generator, Protocol

import altair as alt
from hil.utils.config import ConfigDict, load_config, save_config
from hil.test_scheduler import HeterogenousLoadScheduling, RunsOn
import pathvalidate
import polars as pl
import pytest
from pytest_html import extras as html_extras

from .framework import Trace, record as hil_record
from xdist.remote import Producer
from xdist.scheduler.protocol import Scheduling

from .framework import record as hil_record

logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).parent.parent.parent
ARTIFACTS = REPO_ROOT / "artifacts"
CHART_HEIGHT = 400


class _Config(Protocol):
    """
    A container for pytest configuration data.
    """

    _hil_recorded_trace_paths: dict[str, Path]
    rootdir: Path | str

    def addinivalue_line(self, name: str, line: str) -> None: ...
    def getini(self, name: str) -> list[str] | str | None: ...


class _Node(Protocol):
    """
    A container for pytest node data.
    """

    nodeid: str


class _Request(Protocol):
    """
    A container for pytest request data.
    """

    config: _Config
    node: _Node


class _Item(Protocol):
    """
    A container for pytest item data.
    """

    config: _Config
    nodeid: str


def pytest_addoption(parser: pytest.Parser):
    parser.addini(
        "hil_configs_dir",
        help="directory path relative to rootdir where machine configs are stored (default: <first testpath>/configs)",
    )


def pytest_configure(config: _Config):
    """
    Called after command line options have been parsed and all plugins/initialconftest
    files been loaded. We use this time to initialize a container for storing test records.
    Each entry will map test node ids to the hil.framework.record object created by that test.
    """
    config._hil_recorded_trace_paths = {}  # {node_id: Path}

    # Based on https://docs.pytest.org/en/stable/example/markers.html#custom-marker-and-command-line-option-to-control-test-runs
    config.addinivalue_line(
        "markers",
        "runs_on(hostname: str | None = None) - mark test to run only on specific hostname",
    )


def _should_runs_on(*, hostname: str | None = None) -> bool:
    if hostname is not None and socket.gethostname() != hostname:
        return False

    return True


def pytest_runtest_setup(item):
    # Check the runs_on marker
    runs_on_markers = list(item.iter_markers(name="runs_on"))
    if runs_on_markers and not any(
        _should_runs_on(*m.args, **m.kwargs) for m in runs_on_markers
    ):
        pytest.skip("Skipping test because it is not tagged to run on this environment")


def _save_request_traces(
    request: _Request, traces: list[Trace], logs: list[logging.LogRecord]
) -> None:
    """
    Save the traces for the given request by merging them into a single Polars DataFrame
    and generating an Altair chart. If no data is found, returns None; otherwise, returns
    the Path to the generated HTML chart.
    """
    if not traces:
        return

    # Convert each trace directly to long format and concatenate
    combined = pl.concat(
        [
            pl.DataFrame(
                {
                    "timestamp": trace.timestamps,
                    "trace": [trace.name] * len(trace.timestamps),
                    "value": trace.data,
                }
            )
            for trace in traces
        ]
    ).sort("timestamp")

    logger.debug(combined)

    # If we have no data or only an empty frame, skip
    if combined is None or combined.is_empty():
        logger.debug(f"No data found for {request.node.nodeid}")
        return

    # Base trace chart: a layered line chart with points
    trace_layer = (
        alt.Chart(combined)
        .mark_line(point=True, interpolate="monotone")
        .encode(
            x=alt.X(
                "timestamp:T",
                title="Time",
                axis=alt.Axis(
                    format="%Y-%m-%d %H:%M:%S.%L",
                    labelAngle=-45,
                    tickCount=10,
                    tickMinStep=0.01,
                ),
            ),
            y="value:Q",
            color="trace:N",
            tooltip=[
                alt.Tooltip("timestamp:T", title="Time"),
                alt.Tooltip("trace:N", title="Trace"),
                alt.Tooltip("value:Q", title="Value"),
            ],
        )
    )

    # Convert log records to a list of dicts
    log_data = pl.DataFrame(
        {
            "timestamp": [datetime.fromtimestamp(log.created) for log in logs],
            "log_level": [log.levelname for log in logs],
            "message": [log.getMessage() for log in logs],
        }
    )

    # Create a subtle log layer using mark_rule.
    # The rules are drawn as subtle, dashed vertical lines with tooltips.
    log_layer = (
        alt.Chart(log_data)
        .mark_tick(thickness=6)
        .encode(
            x=alt.X("timestamp:T", title="Time"),
            y=alt.value(0),
            color=alt.Color("log_level:N", title="Level"),
            tooltip=[
                alt.Tooltip("log_level:N", title="Level"),
                alt.Tooltip("message:N", title="Message"),
                alt.Tooltip(
                    "timestamp:T", format="%Y-%m-%d %H:%M:%S.%L", title="Log Time"
                ),
            ],
        )
    )

    # Combine the two layers
    final_chart = (
        alt.layer(trace_layer, log_layer)
        .properties(width="container", height=CHART_HEIGHT)
        .interactive()
    )

    # Save the chart to the designated path
    chart_path = request.config._hil_recorded_trace_paths[request.node.nodeid]
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    final_chart.save(chart_path)


@pytest.fixture(scope="function")
def record(request: _Request, caplog: pytest.LogCaptureFixture):
    """
    A pytest fixture that provides a callable, '_record', for creating and returning
    new hil.framework.record objects to capture time-series data in tests. The resulting
    traces are later turned into Altair charts for inclusion in the pytest-html report.

    Example:
    ----------------------------------------------------------------
    def test_example(record):
        with record(source=lambda: 42, name="demo_trace") as r:
            # do some test steps, collect data...
            pass
    ----------------------------------------------------------------
    """
    traces: list[Trace] = []

    class _record(hil_record):
        @classmethod
        def add_trace(cls, trace: Trace):
            traces.append(trace)

            # This is in a bit of a weird spot because it needs to be called before the
            # report is generated, but this fixture's cleanup is called afterwards
            sanitized_nodeid = (
                pathvalidate.sanitize_filename(request.node.nodeid)
                .replace(":", "-")
                .replace("/", "-")
                .replace(".", "-")
            )
            chart_path = ARTIFACTS / f"{sanitized_nodeid}.html"
            request.config._hil_recorded_trace_paths[request.node.nodeid] = chart_path

    try:
        yield _record
    finally:
        logger.debug(f"Saving {traces} traces for {request.node.nodeid}")
        _save_request_traces(request, traces, caplog.get_records(when="call"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: _Item, call: pytest.CallInfo):
    """
    Called to create a _TestReport for each phase of a test run (setup/call/teardown).
    """
    outcome = yield
    report = outcome.get_result()
    report.extras = getattr(report, "extras", [])

    if call.when == "call" and (
        trace_chart_path := item.config._hil_recorded_trace_paths.get(item.nodeid)
    ):
        # Append the chart HTML to the report extras
        report.extras.append(
            html_extras.url(f"./{trace_chart_path.name}", name="Traces")
        )
        report.extras.append(
            html_extras.html(
                f"<iframe style='width: 100%; height: {CHART_HEIGHT + 150}px; border: none;' src='./{trace_chart_path.name}'></iframe>"
            )
        )


@pytest.fixture(scope="session")
def machine_config(request: _Request) -> Generator[ConfigDict, None, None]:
    # Get the configs_dir from pytest ini options, defaulting to first testpath + /configs
    testpaths = request.config.getini("testpaths")
    if isinstance(testpaths, (list, set, tuple)):
        default_testpath = testpaths[0] if testpaths else "tests"
    else:
        default_testpath = testpaths if testpaths else "tests"
    default_configs_dir = str(Path(default_testpath) / "configs")

    configs_dir = request.config.getini("hil_configs_dir")
    configs_path = Path(str(configs_dir) if configs_dir else default_configs_dir)

    pet_name = socket.gethostname()
    config_obj = load_config(Path(request.config.rootdir) / configs_path, pet_name)
    try:
        yield config_obj
    finally:
        save_config(config_obj, Path(request.config.rootdir) / configs_path, pet_name)


runs_on_key = pytest.StashKey[dict[str, list[RunsOn]]]()


@pytest.hookimpl(tryfirst=True)
def pytest_collection(session: pytest.Session):
    session.config.stash[runs_on_key] = {
        item.nodeid: [
            RunsOn(*m.args, **m.kwargs) for m in item.own_markers if m.name == "runs_on"
        ]
        for item in session.perform_collect()
    }
    session._notfound = []
    session._initial_parts = []
    session._collection_cache = {}
    session.items = []
    session.testscollected = 0
    return True


@pytest.hookimpl
def pytest_xdist_make_scheduler(config: pytest.Config, log: Producer) -> Scheduling:
    try:
        runs_on_by_nodeid = config.stash[runs_on_key]
    except KeyError:
        raise RuntimeError("runs_on_key not found in stash")

    return HeterogenousLoadScheduling(config, log, runs_on_by_nodeid)
