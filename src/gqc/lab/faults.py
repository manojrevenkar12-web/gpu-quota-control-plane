"""The crash and concurrency lab. Each scenario is a handful of clients reserving the same small cluster at once,
with requests retried, steps interleaved at random, workers crashed mid-step, and messages delivered twice and out
of order. After everything has settled, the invariants are checked. The same scenarios (same seed, same luck) run
against the full saga and against variants with one safeguard removed."""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from ..platform.saga import ControlPlane, Safeguards, check_invariants, drive
from ..platform.store import MemoryStore
from ..rng import keyed

VARIANTS: dict[str, Safeguards] = {
    "platform": Safeguards(),
    "no_cas": Safeguards(cas=False),
    "no_idempotency": Safeguards(idempotency=False),
    "no_outbox": Safeguards(outbox=False),
    "no_inbox": Safeguards(inbox=False),
}
P_CRASH = 0.06
P_DUP_DELIVERY = 0.15
P_CONCURRENT_RETRY = 0.25


@dataclass
class Actor:
    kind: str  # api | consumer | relay
    step: Generator[None, None, Any]
    meta: Any


def scenario(seed: int, guard: Safeguards) -> list[str]:
    r = keyed(seed, "faults")  # the same draws for every variant, in the same order
    store = MemoryStore()
    bus: list[dict[str, Any]] = []
    counter = itertools.count()
    cp = ControlPlane(store, lambda: f"r{next(counter):04d}", bus.append, guard)
    cp.set_capacity("c", int(r.integers(6, 14)))
    orgs = ["a", "b", "c"]
    for o in orgs:
        cp.set_quota(o, "c", int(r.integers(3, 12)))
    clients = [(f"k{i}", orgs[int(r.integers(0, 3))], int(r.integers(1, 6))) for i in range(int(r.integers(3, 8)))]
    actors: list[Actor] = []
    tries: Counter[str] = Counter()

    def submit(c: tuple[str, str, int]) -> None:
        tries[c[0]] += 1
        actors.append(Actor("api", cp.create_reservation(c[0], c[1], "c", c[2]), c))

    for c in clients:
        submit(c)
        if r.random() < P_CONCURRENT_RETRY:  # the client times out and retries while the first call still runs
            submit(c)
    for _ in range(4000):
        if not actors and not bus and not any(not v["sent"] for _, _, v in store.scan("outbox")):
            break
        choice = r.random()
        if bus and choice < 0.35:
            msg = bus.pop(int(r.integers(0, len(bus))))
            if r.random() < P_DUP_DELIVERY:
                bus.insert(int(r.integers(0, len(bus) + 1)), msg)
            actors.append(Actor("consumer", cp.handle(msg), msg))
        elif choice < 0.45 and not any(a.kind == "relay" for a in actors):
            actors.append(Actor("relay", cp.relay(), None))
        elif actors:
            a = actors[int(r.integers(0, len(actors)))]
            if r.random() < P_CRASH:
                actors.remove(a)
                a.step.close()
                if a.kind == "api" and tries[a.meta[0]] < 4:
                    submit(a.meta)  # the client retries with the same Idempotency-Key
                elif a.kind == "consumer":
                    bus.append(a.meta)  # not acknowledged: the broker delivers it again
                continue
            try:
                next(a.step)
            except StopIteration:
                actors.remove(a)
    # settle: no more faults; finish what runs, then relay and deliver until nothing is left
    for a in actors:
        drive(a.step)
    for _ in range(100):
        sent = drive(cp.relay())
        if not sent and not bus:
            break
        while bus:
            drive(cp.handle(bus.pop(0)))
    return check_invariants(store)


def run_faults(n: int, base_seed: int) -> dict[str, Any]:
    out: dict[str, Any] = {"scenarios": n, "variants": {}}
    for name, guard in VARIANTS.items():
        kinds: Counter[str] = Counter()
        broken = 0
        for i in range(n):
            bad = scenario(base_seed * 100_000 + i, guard)
            broken += bool(bad)
            kinds.update({b.split(":")[0] for b in bad})
        out["variants"][name] = {"scenarios_broken": broken, "share_broken": broken / n, "by_kind": dict(sorted(kinds.items()))}
    return out
