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

    def check(self, node: WorkerController) -> bool: ...


NodeId = str


class HeterogenousLoadScheduling(LoadScheduling):
    """
    Implement load scheduling across heterogeneous nodes.

    Similar to `LoadScheduling`, except tests are only allocated to compatible worker nodes, as determined by the `runs_on` marker.
    """

    def __init__(
        self,
        config: pytest.Config,
        log: Producer,
        runs_on_by_nodeid: dict[NodeId, list[RunsOn]],
    ):
        self.runs_on_by_nodeid = runs_on_by_nodeid

    @property
    def nodes(self) -> list[WorkerController]: ...

    @property
    def collection_is_completed(self) -> bool: ...

    @property
    def tests_finished(self) -> bool: ...

    @property
    def has_pending(self) -> bool: ...

    def add_node(self, node: WorkerController) -> None: ...

    def add_node_collection(
        self,
        node: WorkerController,
        collection: Sequence[str],
    ) -> None: ...

    def mark_test_complete(
        self,
        node: WorkerController,
        item_index: int,
        duration: float = 0,
    ) -> None: ...

    def mark_test_pending(self, item: str) -> None: ...

    def remove_pending_tests_from_node(
        self,
        node: WorkerController,
        indices: Sequence[int],
    ) -> None: ...

    def remove_node(self, node: WorkerController) -> str | None: ...

    def schedule(self) -> None: ...
