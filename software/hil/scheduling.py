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

    def check_schedule(self, node: WorkerController, duration: float = 0) -> None:
        """Ref: `LoadScheduling.check_schedule`"""
        if node.shutting_down:
            return

        if self.pending:
            compatible_indices = set(self.test_indices_by_worker[node])
            compatible_pending = [i for i in self.pending if i in compatible_indices]

            if not compatible_pending:
                node.shutdown()
                return

            num_nodes = sum(1 for n in self.nodes if self.test_indices_by_worker[n])
            items_per_node_min = max(2, len(compatible_pending) // num_nodes // 4)
            items_per_node_max = max(2, len(compatible_pending) // num_nodes // 2)

            node_pending = self.node2pending[node]
            if len(node_pending) < items_per_node_min:
                if duration >= 0.1 and len(node_pending) >= 2:
                    # Node is busy
                    return

                num_send = items_per_node_max - len(node_pending)
                # Keep at least 2 tests pending even if maxschedchunk=1
                maxschedchunk = max(2 - len(node_pending), self.maxschedchunk)
                self._send_tests(node, min(num_send, maxschedchunk))
        else:
            node.shutdown()

        self.log("num items waiting for node:", len(self.pending))

    def schedule(self) -> None:
        """Ref: `LoadScheduling.schedule`"""

        assert self.collection_is_completed

        if self.collection is not None:
            for node in self.nodes:
                self.check_schedule(node)
            return

        if not self._check_nodes_have_same_collection():
            self.log("**Different tests collected, aborting run**")
            return

        self._check_collection()

        self.collection = next(iter(self.node2collection.values()))
        self.pending[:] = range(len(self.collection))
        if not self.collection:
            return

        if self.maxschedchunk is None:
            self.maxschedchunk = len(self.collection)

        for node in self.nodes:
            if (compatible_tests := len(self.test_indices_by_worker[node])) == 0:
                continue

            items_per_node = compatible_tests // len(self.nodes)
            node_chunksize = min(max(items_per_node // 4, 2), self.maxschedchunk)

            self._send_tests(node, node_chunksize)

        if not self.pending:
            for node in self.nodes:
                node.shutdown()

    def _send_tests(self, node: WorkerController, num: int) -> None:
        compatible_indices = set(self.test_indices_by_worker[node])
        compatible_pending = [i for i in self.pending if i in compatible_indices]
        tests_for_node = compatible_pending[:num]
        if tests_for_node:
            self.pending = [i for i in self.pending if i not in tests_for_node]
            self.node2pending[node].extend(tests_for_node)
            node.send_runtest_some(tests_for_node)
