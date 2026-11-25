"""Admission and rebalancing. A request goes where it asked; a flexible one may go to the same GPU type in
another region; and to make room, the plane may move a flexible reservation that has not started yet."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import ReservationRequest
from .ledger import CapacityLedger


@dataclass
class Placement:
    cluster: str | None
    moved: list[tuple[int, str, str]]  # reservation, from, to


def _same_gpu(ledger: CapacityLedger, cluster: str) -> list[str]:
    gpu = ledger.clusters[cluster].gpu
    return [c for c, k in ledger.clusters.items() if k.gpu == gpu and c != cluster]


def place(
    req: ReservationRequest,
    ledger: CapacityLedger,
    pending: dict[int, ReservationRequest],
    rebalance: bool,
) -> Placement:
    """pending: confirmed reservations that have not started, by id, with where they are held now."""
    if rebalance and req.flexible:  # spread flexible demand: keep room where inflexible customers asked
        here = [req.cluster, *_same_gpu(ledger, req.cluster)]
        best = max(here, key=lambda c: (ledger.headroom(c, req.start, req.end) - req.nodes, c == req.cluster))
        if ledger.fits(best, req.start, req.end, req.nodes):
            return Placement(best, [])
    if ledger.fits(req.cluster, req.start, req.end, req.nodes):
        return Placement(req.cluster, [])
    if not rebalance:
        return Placement(None, [])
    if req.flexible:
        alts = sorted(_same_gpu(ledger, req.cluster), key=lambda c: -ledger.headroom(c, req.start, req.end))
        for c in alts:
            if ledger.fits(c, req.start, req.end, req.nodes):
                return Placement(c, [])
    # move flexible, not-yet-started reservations out of the way, largest overlap first, all or nothing
    cands = [p for p in pending.values() if p.flexible and ledger.holds[p.id][0] == req.cluster and p.start < req.end and req.start < p.end]
    cands.sort(key=lambda p: (-p.nodes, p.id))
    moved: list[tuple[int, str, str]] = []
    for p in cands:
        for c in sorted(_same_gpu(ledger, req.cluster), key=lambda c: -ledger.headroom(c, p.start, p.end)):
            if ledger.fits(c, p.start, p.end, p.nodes):
                ledger.move(p.id, c)
                moved.append((p.id, req.cluster, c))
                break
        if ledger.fits(req.cluster, req.start, req.end, req.nodes):
            return Placement(req.cluster, moved)
    for rid, frm, to in reversed(moved):  # undo: no half-done rebalance
        ledger.move(rid, frm)
        _ = to
    return Placement(None, [])
