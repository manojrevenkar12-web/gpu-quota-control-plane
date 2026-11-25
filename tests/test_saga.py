import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from gqc.lab.faults import VARIANTS, run_faults, scenario
from gqc.platform.saga import ControlPlane, Safeguards, check_invariants, drive
from gqc.platform.store import MemoryStore, SQLiteStore


def plane(store: Any = None, guard: Safeguards | None = None) -> tuple[ControlPlane, list[dict[str, Any]]]:
    bus: list[dict[str, Any]] = []
    n = itertools.count()
    cp = ControlPlane(store or MemoryStore(), lambda: f"r{next(n)}", bus.append, guard or Safeguards())
    return cp, bus


def settle(cp: ControlPlane, bus: list[dict[str, Any]]) -> None:
    for _ in range(50):
        sent = drive(cp.relay())
        if not sent and not bus:
            return
        while bus:
            drive(cp.handle(bus.pop(0)))


def test_happy_path_confirms_and_holds() -> None:
    cp, bus = plane()
    cp.set_capacity("c", 10)
    cp.set_quota("a", "c", 8)
    rid = drive(cp.create_reservation("k1", "a", "c", 4))
    settle(cp, bus)
    assert cp.reservation(rid)["state"] == "confirmed"  # type: ignore[index]
    assert check_invariants(cp.store) == []


def test_over_quota_is_compensated_and_capacity_returned() -> None:
    cp, bus = plane()
    cp.set_capacity("c", 10)
    cp.set_quota("a", "c", 3)
    rid = drive(cp.create_reservation("k1", "a", "c", 4))
    settle(cp, bus)
    r = cp.reservation(rid)
    assert r is not None and r["state"] == "rejected" and r["reason"] == "over quota"
    assert cp.store.read("capacity", "c")[1]["free"] == 10
    assert check_invariants(cp.store) == []


def test_no_capacity_is_rejected() -> None:
    cp, bus = plane()
    cp.set_capacity("c", 3)
    cp.set_quota("a", "c", 8)
    rid = drive(cp.create_reservation("k1", "a", "c", 4))
    settle(cp, bus)
    assert cp.reservation(rid)["reason"] == "no capacity"  # type: ignore[index]


def test_a_retry_with_the_same_key_returns_the_same_reservation() -> None:
    cp, bus = plane()
    cp.set_capacity("c", 10)
    cp.set_quota("a", "c", 8)
    a = drive(cp.create_reservation("k1", "a", "c", 4))
    b = drive(cp.create_reservation("k1", "a", "c", 4))
    settle(cp, bus)
    assert a == b and len(cp.store.scan("reservations")) == 1


def test_a_duplicated_message_is_applied_once() -> None:
    cp, bus = plane()
    cp.set_capacity("c", 10)
    cp.set_quota("a", "c", 8)
    drive(cp.create_reservation("k1", "a", "c", 4))
    drive(cp.relay())
    bus.append(dict(bus[0]))
    settle(cp, bus)
    assert cp.store.read("capacity", "c")[1]["free"] == 6
    assert check_invariants(cp.store) == []


def test_the_full_saga_survives_the_lab_and_every_safeguard_matters() -> None:
    res = run_faults(120, 3)["variants"]
    assert res["platform"]["scenarios_broken"] == 0
    for name in VARIANTS:
        if name != "platform":
            assert res[name]["scenarios_broken"] > 0, name


def test_a_scenario_is_reproducible() -> None:
    assert scenario(42, Safeguards(inbox=False)) == scenario(42, Safeguards(inbox=False))


def test_sqlite_threads_never_oversell(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    lock = threading.Lock()
    bus: list[dict[str, Any]] = []
    n = itertools.count()

    def send(m: dict[str, Any]) -> None:
        with lock:
            bus.append(m)

    cp = ControlPlane(store, lambda: f"r{next(n)}", send)
    cp.set_capacity("c", 20)
    for o in ("a", "b", "c", "d"):
        cp.set_quota(o, "c", 12)

    def client(i: int) -> None:
        drive(cp.create_reservation(f"k{i}", "abcd"[i % 4], "c", 3))
        drive(cp.relay())
        while True:
            with lock:
                if not bus:
                    return
                msg = bus.pop(0)
            drive(cp.handle(msg))

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(client, range(24)))
    for _ in range(20):
        drive(cp.relay())
        while bus:
            drive(cp.handle(bus.pop(0)))
    assert check_invariants(store) == []
    confirmed = [v for _, _, v in store.scan("reservations") if v["state"] == "confirmed"]
    assert sum(v["nodes"] for v in confirmed) <= 20 and len(confirmed) == 6
