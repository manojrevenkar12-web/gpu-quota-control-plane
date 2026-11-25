"""Shapes shared by the control plane, the simulation and the service. No behaviour here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"  # capacity held for [start, end)
    ACTIVE = "active"  # the customer has started using it; billing runs
    NOTICED = "noticed"  # unused past the grace period; the customer has been asked
    RECLAIMED = "reclaimed"  # released after an unanswered notice
    EXPIRED = "expired"
    REJECTED = "rejected"


TERMINAL = {State.RECLAIMED, State.EXPIRED, State.REJECTED}
TRANSITIONS: dict[State, set[State]] = {
    State.REQUESTED: {State.CONFIRMED, State.REJECTED},
    State.CONFIRMED: {State.ACTIVE, State.NOTICED, State.EXPIRED},
    State.NOTICED: {State.ACTIVE, State.CONFIRMED, State.RECLAIMED, State.EXPIRED},
    State.ACTIVE: {State.EXPIRED},
    State.RECLAIMED: set(),
    State.EXPIRED: set(),
    State.REJECTED: set(),
}


class IllegalTransition(ValueError):
    pass


def advance(current: State, target: State) -> State:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current.value} -> {target.value}")
    return target


@dataclass(frozen=True)
class Cluster:
    name: str
    region: str
    gpu: str
    nodes: int


@dataclass(frozen=True)
class ReservationRequest:
    id: int
    customer: str
    tier: str
    cluster: str
    flexible: bool  # the customer accepts the same GPU type in another region
    nodes: int
    start: int
    end: int


@dataclass(frozen=True)
class QuotaAsk:
    id: int
    org: int
    service: str
    current: int
    asked: int
    signals: dict[str, float]
