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
from typing import Protocol
from functools import reduce

import altair as alt
import pytest

from .framework import record as hil_record

logger = logging.getLogger(__name__)


class _Config(Protocol):
    """
    A container for pytest configuration data.
    """

    _hil_recorded_traces: defaultdict[str, list[hil_record]]


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

    def _record(*args, **kwargs) -> hil_record:
        """
        Create and return a new hil_record instance, storing it for the current test.
        Any arguments or keyword arguments are passed to hil.framework.record.__init__.
        """
        rec = hil_record(*args, **kwargs)
        request.config._hil_recorded_traces[request.node.nodeid].append(rec)
        return rec

    yield _record


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: _Item, call: pytest.CallInfo):
    """
    Called to create a _TestReport for each phase of a test run (setup/call/teardown).
    """
    outcome = yield
    report = outcome.get_result()
    report.extras = getattr(report, "extras", [])

    if call.when == "call":
        # Retrieve ALL record objects we stored for this test node.
        print(f"Retrieving records for {item.nodeid}")
        records = item.config._hil_recorded_traces.get(item.nodeid, [])
        if not records:
            print(f"No records found for {item.nodeid}")
            return
        print(f"Found {len(records)} records for {item.nodeid}")

        # Combine all records into one Polars DataFrame, joining on "timestamp"
        combined = reduce(
            lambda left, right: left.join(
                right, on="timestamp", how="full", coalesce=True
            ),
            (rec.trace.to_polars() for rec in records),
        ).sort("timestamp")

        print(combined)

        # If we have no data or only an empty frame, skip
        if combined is None or combined.is_empty():
            print(f"No data found for {item.nodeid}")
            return

        # Get all non-timestamp column names (these are our trace names)
        trace_names = [col for col in combined.columns if col != "timestamp"]
        print(trace_names)

        # Create a layered chart with one line per trace
        base = alt.Chart(combined).encode(
            x=alt.X(
                "timestamp:T",
                title="Time",
                axis=alt.Axis(
                    format="%H:%M:%S.%L",  # Show hours:minutes:seconds.milliseconds
                    labelAngle=-45,  # Angle the labels for better readability
                ),
            )
        )

        layers = []
        for trace_name in trace_names:
            layer = base.mark_line().encode(
                y=alt.Y(f"{trace_name}:Q", title=trace_name),
                color=alt.Color(f"{trace_name}:N", title=trace_name),
                tooltip=[
                    alt.Tooltip("timestamp:T", title="Time"),
                    alt.Tooltip(f"{trace_name}:Q", title=trace_name),
                ],
            )
            layers.append(layer)

        # Combine all layers into one chart
        chart = (
            alt.layer(*layers)
            .properties(width=600, height=400, title=f"Test Traces: {item.nodeid}")
            .configure_axis(
                gridColor="#f6f6f6",  # Lighter grid lines
                domainColor="#ccc",  # Lighter axis lines
            )
        )

        # Instead of adding a new column, add our chart as extra content so it appears under the log.
        # try:
        #     # from pytest_html import extras as html_extras
        #     # report.extras.append(html_extras.html(chart.to_html(fullhtml=False)))
        #     # print("Added HiL Trace extras")
        # except ImportError:
        #     print("pytest-html is not installed")
        chart.save("chart.html")
