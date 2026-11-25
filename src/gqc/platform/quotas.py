"""Quota requests. A score from visible signals sends low-risk, modest requests through at once; the rest wait for
a person. "manual" sends everything to a person; "approve_all" approves everything at once."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..domain import QuotaAsk


def risk(ask: QuotaAsk, w: dict[str, float]) -> float:
    s = ask.signals
    r = 0.0
    r += w["new_account"] * (s["account_age_days"] < 14)
    r += w["payment_unverified"] * (s["payment_verified"] < 0.5)
    r += w["no_prior_spend"] * (s["prior_spend_eur"] <= 0)
    r += w["single_member"] * (s["team_members"] <= 1)
    r += w["big_jump"] * (ask.asked > 4 * max(ask.current, 1))
    r += w["flat_out"] * (s.get("at_quota_share_24h", 0.0) >= 0.95)  # pinned at its quota around the clock
    return min(1.0, r)


def route(ask: QuotaAsk, mode: str, cfg: dict[str, Any]) -> str:
    """ "approve" now or "review" by a person."""
    if mode == "approve_all":
        return "approve"
    if mode == "manual":
        return "review"
    ok = ask.asked <= int(cfg["auto_approve_max_nodes"]) and risk(ask, cfg["risk_weights"]) <= float(cfg["auto_approve_risk_max"])
    return "approve" if ok else "review"


@dataclass
class ReviewQueue:
    """First in, first out; analysts spend a fixed number of minutes per step on it."""

    minutes_per_review: float
    minutes_per_step: float
    queue: deque[tuple[QuotaAsk, int]] = field(default_factory=deque)
    credit: float = 0.0

    def push(self, ask: QuotaAsk, step: int) -> None:
        self.queue.append((ask, step))

    def work(self) -> list[tuple[QuotaAsk, int]]:
        """Requests a person finishes in this step."""
        self.credit += self.minutes_per_step
        done = []
        while self.queue and self.credit >= self.minutes_per_review:
            self.credit -= self.minutes_per_review
            done.append(self.queue.popleft())
        if not self.queue:
            self.credit = min(self.credit, self.minutes_per_review)
        return done
