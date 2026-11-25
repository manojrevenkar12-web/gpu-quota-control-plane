"""Sharing contested preemptible capacity. "fair" is weighted max-min (water-filling): nobody gets more than
they asked, and leftover goes to whoever still wants more, in proportion to weight. "fifo" serves the earliest
arrivals in full first."""

from __future__ import annotations

import numpy as np


def water_fill(asks: np.ndarray, weights: np.ndarray, capacity: int) -> np.ndarray:
    asks = asks.astype(float)
    out = np.zeros_like(asks)
    if capacity <= 0 or asks.sum() == 0:
        return out.astype(int)
    if asks.sum() <= capacity:
        return asks.astype(int)
    active = asks > 0
    left = float(capacity)
    while left > 1e-9 and active.any():
        share = left * weights * active / (weights * active).sum()
        need = asks - out
        give = np.minimum(share, need)
        out += give
        left -= give.sum()
        active = active & (asks - out > 1e-9)
        if give.sum() < 1e-9:
            break
    # whole nodes: floor, then hand out the remainder by largest fraction (deterministic)
    base = np.floor(out + 1e-9)
    rem = round(capacity - float(base.sum()))
    frac = out - base
    order = np.lexsort((np.arange(len(out)), -frac))
    for i in order[: max(rem, 0)]:
        if base[i] < asks[i]:
            base[i] += 1
    return base.astype(int)


def fifo(asks: np.ndarray, order: np.ndarray, capacity: int) -> np.ndarray:
    out = np.zeros(len(asks), dtype=int)
    left = int(capacity)
    for i in order:
        g = min(int(asks[i]), left)
        out[i] = g
        left -= g
        if left <= 0:
            break
    return out


def jain(x: np.ndarray) -> float:
    """1.0 when everyone gets the same share of what they asked; 1/n when one org gets it all."""
    if len(x) == 0 or (x**2).sum() == 0:
        return 1.0
    return float(x.sum() ** 2 / (len(x) * (x**2).sum()))
