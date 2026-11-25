"""What each cluster has promised, step by step. A reservation holds its nodes over [start, end)."""

from __future__ import annotations

import numpy as np

from ..domain import Cluster


class CapacityLedger:
    def __init__(self, clusters: dict[str, Cluster], steps: int, reservable_share: float) -> None:
        self.clusters = clusters
        self.steps = steps
        self.cap = {c: int(np.floor(k.nodes * reservable_share)) for c, k in clusters.items()}
        self.booked = {c: np.zeros(steps, dtype=int) for c in clusters}
        self.holds: dict[int, tuple[str, int, int, int]] = {}  # reservation -> cluster, nodes, start, end

    def headroom(self, cluster: str, start: int, end: int) -> int:
        return int(self.cap[cluster] - self.booked[cluster][start:end].max(initial=0))

    def fits(self, cluster: str, start: int, end: int, nodes: int) -> bool:
        return self.headroom(cluster, start, end) >= nodes

    def hold(self, rid: int, cluster: str, nodes: int, start: int, end: int) -> None:
        assert rid not in self.holds and self.fits(cluster, start, end, nodes)
        self.booked[cluster][start:end] += nodes
        self.holds[rid] = (cluster, nodes, start, end)

    def release_from(self, rid: int, step: int) -> None:
        """Give back what is left of a hold from this step on."""
        cluster, nodes, start, end = self.holds.pop(rid)
        a = max(step, start)
        if a < end:
            self.booked[cluster][a:end] -= nodes
        if a > start:
            self.holds[rid] = (cluster, nodes, start, a)

    def move(self, rid: int, to: str) -> None:
        cluster, nodes, start, end = self.holds.pop(rid)
        self.booked[cluster][start:end] -= nodes
        self.hold(rid, to, nodes, start, end)

    def check(self) -> None:
        for c, b in self.booked.items():
            assert (b >= 0).all() and (b <= self.cap[c]).all(), c
