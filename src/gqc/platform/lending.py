"""Lending idle reserved nodes to the preemptible pool. The plane forecasts the next step's use of each reservation
and lends only what lies above the forecast plus a buffer, so that taking nodes back (one step, preempting
preemptible jobs) almost never leaves a customer short. "naive" lends everything idle; "off" lends nothing."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Lender:
    nodes: int
    mode: str  # off | naive | buffered
    spd: int
    warmup: int
    window: int
    quantile: float
    min_buffer: int
    seen: list[int] = field(default_factory=list)
    errors: list[int] = field(default_factory=list)
    last_forecast: int | None = None

    def forecast(self) -> int:
        u = self.seen
        k = len(u)
        if self.mode == "naive":
            return u[-1]
        picks = [u[-1]]
        for back in (self.spd, 7 * self.spd):
            if k >= back:
                picks += u[k - back : k - back + 2]
        return int(max(picks))

    def lend(self) -> int:
        """Nodes to lend for the next step."""
        if self.mode == "off" or len(self.seen) < self.warmup:
            self.last_forecast = None
            return 0
        f = self.forecast()
        self.last_forecast = f
        if self.mode == "naive":
            return max(0, self.nodes - f)
        tail = self.errors[-self.window :]
        q = int(np.ceil(np.quantile(tail, self.quantile))) if tail else self.nodes
        buffer = max(self.min_buffer, q)
        return int(np.clip(self.nodes - f - buffer, 0, self.nodes))

    def observe(self, used: int) -> None:
        if self.last_forecast is not None:
            self.errors.append(max(0, used - self.last_forecast))
        self.seen.append(used)
