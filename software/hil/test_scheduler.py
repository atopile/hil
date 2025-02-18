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
        return self.hostname == node.gateway.remoteaddress


NodeId = str


class HeterogenousLoadScheduling(LoadScheduling):
    """
    Implement load scheduling across heterogeneous nodes.

    Similar to `LoadScheduling`, except tests are only allocated to compatible worker nodes.
    Affinity is determined by the `runs_on` marker.

    Attributes:
        runs_on_by_nodeid: Mapping of test node ids to RunsOn records.
        nodeids_by_worker: Mapping of workers to the node ids that they are compatible with.
    """

    def __init__(
        self,
        config: pytest.Config,
        log: Producer,
        runs_on_by_nodeid: dict[NodeId, list[RunsOn]],
    ):
        self.runs_on_by_nodeid = runs_on_by_nodeid
        self.nodeids_by_worker: dict[WorkerController, list[NodeId]] = {}
        super().__init__(config, log)

    def add_node(self, node: WorkerController) -> None:
        super().add_node(node)
        self.nodeids_by_worker[node] = []

    def add_node_collection(
        self, node: WorkerController, collection: Sequence[str]
    ) -> None:
        super().add_node_collection(node, collection)
        self.nodeids_by_worker[node] = [
            nodeid
            for nodeid in collection
            if any(run_on.check(node) for run_on in self.runs_on_by_nodeid[nodeid])
        ]
