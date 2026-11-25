"""Reservations nobody has started. After the grace period with zero use the plane sends a notice; an answer of
"keep it" keeps the reservation, no answer by the deadline releases the capacity from that step on."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import State, advance


@dataclass
class ReclaimClock:
    grace_steps: int
    notice_steps: int

    def due(self, state: State, start: int, step: int, used_so_far: int, noticed_at: int | None) -> str | None:
        """What to do at this step: "notice", "reclaim" or nothing."""
        if used_so_far > 0 or state not in (State.CONFIRMED, State.NOTICED):
            return None
        if state == State.CONFIRMED and step >= start + self.grace_steps:
            return "notice"
        if state == State.NOTICED and noticed_at is not None and step >= noticed_at + self.notice_steps:
            return "reclaim"
        return None


def on_answer(state: State, keep: bool) -> State:
    return advance(state, State.CONFIRMED if keep else State.NOTICED)
