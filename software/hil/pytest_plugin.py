"""
Pytest plugin providing a 'record' fixture and hooking into pytest-html to display
Altair plots for recorded traces.

References:
    - https://pytest-html.readthedocs.io/en/latest/api_reference.html
    - https://altair-viz.github.io/
    - The 'record' class is from hil.framework in this same package.
"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Protocol

import altair as alt
import pathvalidate
import polars as pl
import pytest
from pytest_html import extras as html_extras

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


def pytest_configure(config: _Config):
    """
    Called after command line options have been parsed and all plugins/initialconftest
    files been loaded. We use this time to initialize a container for storing test records.
    Each entry will map test node ids to the hil.framework.record object created by that test.
    """
    config._hil_recorded_traces = defaultdict(list)  # {node_id: [hil_record]}
    config._hil_recorded_trace_paths = {}  # {node_id: Path}


def _save_request_traces(request: _Request, recs: list[hil_record]) -> Path | None:
    """
    Save the traces for the given request.
    """
    if not recs or request.node.nodeid not in request.config._hil_recorded_trace_paths:
        return

    # Convert each trace directly to long format and concatenate
    combined = pl.concat(
        [
            pl.DataFrame(
                {
                    "timestamp": rec.trace.timestamps,
                    "trace": [rec.trace.name] * len(rec.trace.timestamps),
                    "value": rec.trace.data,
                }
            )
            for rec in recs
        ]
    ).sort("timestamp")

    logger.debug(combined)

    # If we have no data or only an empty frame, skip
    if combined is None or combined.is_empty():
        logger.debug(f"No data found for {request.node.nodeid}")
        return

    # Create a layered chart with one line per trace
    chart = (
        alt.Chart(combined)
        .mark_line(interpolate="monotone")
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
        )
        .properties(width="container", height=CHART_HEIGHT)
        .interactive()
    )

    # Add points to the chart
    points = (
        alt.Chart(combined)
        .mark_point()
        .encode(
            x="timestamp:T",
            y="value:Q",
            color="trace:N",
            tooltip=[
                alt.Tooltip("trace:N", title="Trace"),
                alt.Tooltip("timestamp:T", title="Timestamp"),
                alt.Tooltip("value:Q", title="Value"),
            ],
        )
    )

    # Combine line and points
    final_chart = chart + points
    chart_path = request.config._hil_recorded_trace_paths[request.node.nodeid]
    final_chart.save(chart_path)
    return chart_path


@pytest.fixture(scope="function")
def record(request: _Request):
    """
    A pytest fixture that provides a callable named '_record' which creates and returns
    a new hil.framework.record object (wrapped in an instance of hil_record). This record
    is stored in config._hil_recorded_traces, so that after the test we can extract the
    trace data and produce an Altair chart in the pytest-html report.

    Usage example:
    ----------------------------------------------------------------
    def test_something(record):
        with record(source=lambda: 42, name="test_trace") as r:
            # ... do some test steps ...
    ----------------------------------------------------------------
    """
    recs: list[hil_record] = []

    def _record(*args, **kwargs) -> hil_record:
        """
        Create and return a new hil_record instance, storing it for the current test.
        Any arguments or keyword arguments are passed to hil.framework.record.__init__.
        """
        rec = hil_record(*args, **kwargs)
        recs.append(rec)
        if request.node.nodeid not in request.config._hil_recorded_trace_paths:
            sanitized_nodeid = (
                pathvalidate.sanitize_filename(request.node.nodeid)
                .replace(":", "-")
                .replace("/", "-")
                .replace(".", "-")
            )
            chart_path = ARTIFACTS / f"{sanitized_nodeid}.html"
            request.config._hil_recorded_trace_paths[request.node.nodeid] = chart_path
        return rec

    try:
        yield _record
    finally:
        _save_request_traces(request, recs)


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
