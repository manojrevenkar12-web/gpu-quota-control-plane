"""Creating a reservation is a saga across three owners: the reservation record, the cluster's capacity and the
organisation's quota. Each step is one local transaction; messages between steps go through an outbox written in
the same transaction (no dual write), are delivered at least once, and are de-duplicated by an inbox. A step that
cannot go on queues its compensation.

Every step is a generator: it yields between reading and committing, so the lab can interleave steps, crash them
mid-way and deliver messages twice. `drive` runs one to the end, as the service does.

Lab switches turn off one safeguard each: cas (version check), idempotency (Idempotency-Key), outbox, inbox."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any

from .store import Conflict, Store, Tx

type Step[T] = Generator[None, None, T]
OPEN = {"requested", "held", "compensating"}
FINAL = {"confirmed", "rejected"}


def drive[T](step: Step[T]) -> T:
    try:
        while True:
            next(step)
    except StopIteration as stop:
        value: T = stop.value
        return value


@dataclass
class Safeguards:
    cas: bool = True
    idempotency: bool = True
    outbox: bool = True
    inbox: bool = True


@dataclass
class ControlPlane:
    store: Store
    new_id: Callable[[], str]
    send: Callable[[dict[str, Any]], None]  # the message bus (used directly only without an outbox)
    guard: Safeguards = field(default_factory=Safeguards)
    max_attempts: int = 8

    # setup ------------------------------------------------------------------------------------------------
    def set_capacity(self, cluster: str, nodes: int) -> None:
        tx = Tx(self.store)
        cur = tx.get("capacity", cluster) or {"total": 0, "free": 0, "holds": {}}
        held = sum(cur["holds"].values())
        if nodes < held:
            raise ValueError(f"{cluster}: {held} nodes are held, cannot shrink to {nodes}")
        tx.put("capacity", cluster, {"total": nodes, "free": nodes - held, "holds": cur["holds"]})
        tx.commit()

    def set_quota(self, org: str, service: str, limit: int) -> None:
        tx = Tx(self.store)
        cur = tx.get("quota", f"{org}/{service}") or {"limit": 0, "used": 0}
        if limit < cur["used"]:
            raise ValueError(f"{org}/{service}: {cur['used']} in use, cannot lower the limit to {limit}")
        tx.put("quota", f"{org}/{service}", {"limit": limit, "used": cur["used"]})
        tx.commit()

    # the API step -----------------------------------------------------------------------------------------
    def create_reservation(self, idem_key: str, org: str, cluster: str, nodes: int) -> Step[str]:
        rid = self.new_id()
        for _ in range(self.max_attempts):
            tx = Tx(self.store, self.guard.cas)
            if self.guard.idempotency:
                existing = tx.get("idem", idem_key)
                if existing is not None:
                    return str(existing)
            r = {"id": rid, "org": org, "cluster": cluster, "nodes": nodes, "state": "requested", "idem": idem_key, "reason": None}
            tx.put("reservations", rid, r)
            if self.guard.idempotency:
                tx.put("idem", idem_key, rid)
            msg = {"id": f"{rid}:hold", "type": "hold", "rid": rid}
            if self.guard.outbox:
                tx.put("outbox", msg["id"], {**msg, "sent": False})
            yield
            try:
                tx.commit()
            except Conflict:
                continue
            if not self.guard.outbox:
                yield  # a crash here loses the message: the dual write the outbox exists to avoid
                self.send(msg)
            return rid
        raise Conflict("create_reservation: too many conflicts")

    # the relay --------------------------------------------------------------------------------------------
    def relay(self, batch: int = 64) -> Step[int]:
        """Send what the outbox holds, then mark it sent. A crash in between sends it again later."""
        pending = [(k, v) for k, _, v in self.store.scan("outbox") if not v["sent"]][:batch]
        for k, v in pending:
            self.send({x: v[x] for x in v if x != "sent"})
            yield
            tx = Tx(self.store)
            cur = tx.get("outbox", k)
            if cur is not None and not cur["sent"]:
                tx.put("outbox", k, {**cur, "sent": True})
                with contextlib.suppress(Conflict):
                    tx.commit()
        return len(pending)

    # the consumers ----------------------------------------------------------------------------------------
    def handle(self, msg: dict[str, Any]) -> Step[None]:
        for _ in range(self.max_attempts):
            tx = Tx(self.store, self.guard.cas)
            if self.guard.inbox and tx.get("inbox", msg["id"]) is not None:
                return
            r = tx.get("reservations", msg["rid"])
            if r is None:
                return
            getattr(self, "_" + msg["type"])(tx, r)
            if self.guard.inbox:
                tx.put("inbox", msg["id"], True)
            yield
            try:
                tx.commit()
                return
            except Conflict:
                continue
        raise Conflict(f"handle {msg['id']}: too many conflicts")

    def _emit(self, tx: Tx, msg: dict[str, Any]) -> None:
        if self.guard.outbox:
            tx.put("outbox", msg["id"], {**msg, "sent": False})
        else:
            self.send(msg)

    def _hold(self, tx: Tx, r: dict[str, Any]) -> None:
        if self.guard.inbox and r["state"] != "requested":
            return
        cap = tx.get("capacity", r["cluster"])
        if cap is None or cap["free"] < r["nodes"]:
            r.update(state="rejected", reason="no capacity")
        else:
            cap["free"] -= r["nodes"]
            cap["holds"][r["id"]] = cap["holds"].get(r["id"], 0) + r["nodes"]
            tx.put("capacity", r["cluster"], cap)
            r["state"] = "held"
            self._emit(tx, {"id": f"{r['id']}:quota", "type": "quota", "rid": r["id"]})
        tx.put("reservations", r["id"], r)

    def _quota(self, tx: Tx, r: dict[str, Any]) -> None:
        if self.guard.inbox and r["state"] != "held":
            return
        key = f"{r['org']}/{r['cluster']}"
        q = tx.get("quota", key) or {"limit": 0, "used": 0}
        if q["used"] + r["nodes"] <= q["limit"]:
            q["used"] += r["nodes"]
            tx.put("quota", key, q)
            r["state"] = "confirmed"
        else:
            r.update(state="compensating", reason="over quota")
            self._emit(tx, {"id": f"{r['id']}:release", "type": "release", "rid": r["id"]})
        tx.put("reservations", r["id"], r)

    def _release(self, tx: Tx, r: dict[str, Any]) -> None:
        if self.guard.inbox and r["state"] != "compensating":
            return
        cap = tx.get("capacity", r["cluster"])
        cap["free"] += cap["holds"].pop(r["id"], 0)
        tx.put("capacity", r["cluster"], cap)
        r["state"] = "rejected"
        tx.put("reservations", r["id"], r)

    # reading ----------------------------------------------------------------------------------------------
    def reservation(self, rid: str) -> dict[str, Any] | None:
        r: dict[str, Any] | None = self.store.read("reservations", rid)[1]
        return r


def check_invariants(store: Store) -> list[str]:
    """What must hold once every message has been handled. Empty means sound."""
    bad: list[str] = []
    res = {k: v for k, _, v in store.scan("reservations")}
    for c, _, cap in store.scan("capacity"):
        held = sum(cap["holds"].values())
        if cap["free"] < 0 or held > cap["total"]:
            bad.append(f"overheld:{c}")
        if cap["free"] + held != cap["total"]:
            bad.append(f"capacity_drift:{c}")
        for rid in cap["holds"]:
            if res.get(rid, {}).get("state") not in ("held", "confirmed", "compensating"):
                bad.append(f"orphan_hold:{rid}")
        promised = [x for x in res.values() if x["cluster"] == c and x["state"] in ("held", "confirmed")]
        if sum(x["nodes"] for x in promised) > cap["total"]:
            bad.append(f"oversold:{c}")
        bad += [f"unbacked:{x['id']}" for x in promised if cap["holds"].get(x["id"], 0) != x["nodes"]]
    by_key: dict[str, int] = {}
    for r in res.values():
        if r["state"] != "rejected":
            by_key[r["idem"]] = by_key.get(r["idem"], 0) + 1
        if r["state"] in OPEN:
            bad.append(f"stuck:{r['id']}")
    bad += [f"duplicate:{k}" for k, n in by_key.items() if n > 1]
    for key, _, q in store.scan("quota"):
        org, cluster = key.split("/", 1)
        used = sum(r["nodes"] for r in res.values() if r["org"] == org and r["cluster"] == cluster and r["state"] == "confirmed")
        if q["used"] != used or q["used"] > q["limit"]:
            bad.append(f"quota_drift:{key}")
    return bad
