from collections.abc import Sequence
from dataclasses import dataclass
import pytest
from xdist.scheduler.load import LoadScheduling
from xdist.workermanage import WorkerController
from xdist.remote import Producer


@dataclass
class RunsOn:
    hostname: str | None

    def __init__(self, *args, hostname: str | None = None):
        self.hostname = hostname

    def check(self, node: WorkerController) -> bool:
        # FIXME
        return self.hostname is None or self.hostname == node.gateway.id


class HeterogenousLoadScheduling(LoadScheduling):
    """
    Implement load scheduling across heterogeneous nodes.

    Similar to `LoadScheduling`, except tests are only allocated to compatible worker nodes.
    Affinity is determined by the `runs_on` marker.

    Attributes:
        runs_on_by_test_name: Mapping of test names to RunsOn records.
        test_names_by_worker: Mapping of workers to the test names that they are compatible with.
        test_indices_by_worker: Mapping of workers to the indices of the tests that they are compatible with.
    """

    def __init__(
        self,
        config: pytest.Config,
        log: Producer,
        runs_on_by_test_name: dict[str, list[RunsOn]],
    ):
        self.runs_on_by_test_name = runs_on_by_test_name
        self.test_names_by_worker: dict[WorkerController, list[str]] = {}
        self.test_indices_by_worker: dict[WorkerController, list[int]] = {}
        super().__init__(config, log)

    def add_node(self, node: WorkerController) -> None:
        super().add_node(node)
        self.test_names_by_worker[node] = []

    def add_node_collection(
        self, node: WorkerController, collection: Sequence[str]
    ) -> None:
        super().add_node_collection(node, collection)

        # TODO: ensure there is a local worker called "local"
        if node.gateway.id == "local":
            self.test_names_by_worker[node] = [
                test_name
                for test_name in collection
                if not self.runs_on_by_test_name[test_name]
            ]
        else:
            self.test_names_by_worker[node] = [
                test_name
                for test_name in collection
                if any(
                    runs_on.check(node)
                    for runs_on in self.runs_on_by_test_name[test_name]
                )
            ]

        self.test_indices_by_worker[node] = [
            collection.index(test_name) for test_name in self.test_names_by_worker[node]
        ]

    def _check_collection(self):
        """
        Check if every test has a compatible worker.
        """

        for test_name, runs_on_list in self.runs_on_by_test_name.items():
            if not runs_on_list:
                continue

            for runs_on in runs_on_list:
                if any(runs_on.check(node) for node in self.nodes):
                    break
            else:
                raise ValueError(
                    f"Test {test_name} has no compatible worker: requires one of {runs_on_list}"
                )

    def schedule(self) -> None:
        # FIXME: close review

        assert self.collection_is_completed

        # If already scheduled, just check schedules
        if self.collection is not None:
            for node in self.nodes:
                self.check_schedule(node)
            return

        # Verify collections are identical
        if not self._check_nodes_have_same_collection():
            self.log("**Different tests collected, aborting run**")
            return

        self._check_collection()

        print(self.test_names_by_worker)
        print(self.test_indices_by_worker)

        # Initialize collection and pending tests
        self.collection = next(iter(self.node2collection.values()))
        self.pending[:] = range(len(self.collection))
        if not self.collection:
            return

        if self.maxschedchunk is None:
            self.maxschedchunk = len(self.collection)

        # For each node, calculate how many tests it should initially receive
        for node in self.nodes:
            compatible_tests = len(self.test_indices_by_worker[node])
            if compatible_tests == 0:
                continue

            # Calculate initial chunk size for this node
            items_per_node = compatible_tests // len(self.nodes)
            node_chunksize = min(max(items_per_node // 4, 2), self.maxschedchunk)

            # Send initial batch of tests
            self._send_tests(node, node_chunksize)

        # If no more pending tests, start shutting down nodes
        if not self.pending:
            for node in self.nodes:
                node.shutdown()

    def _send_tests(self, node: WorkerController, num: int) -> None:
        compatible_indices = set(self.test_indices_by_worker[node])
        compatible_pending = [i for i in self.pending if i in compatible_indices]
        tests_for_node = compatible_pending[:num]
        print(f"sending {tests_for_node} to {node}")
        if tests_for_node:
            self.pending = [i for i in self.pending if i not in tests_for_node]
            self.node2pending[node].extend(tests_for_node)
            node.send_runtest_some(tests_for_node)
