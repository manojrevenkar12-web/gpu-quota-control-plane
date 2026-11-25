import numpy as np
import pytest

from gqc.domain import Cluster, IllegalTransition, QuotaAsk, ReservationRequest, State, advance
from gqc.platform.fairness import fifo, jain, water_fill
from gqc.platform.ledger import CapacityLedger
from gqc.platform.lending import Lender
from gqc.platform.placement import place
from gqc.platform.quotas import ReviewQueue, risk, route

CL = {
    "n-h200": Cluster("n-h200", "n", "H200", 10),
    "w-h200": Cluster("w-h200", "w", "H200", 10),
    "n-b200": Cluster("n-b200", "n", "B200", 10),
}


def req(i: int, cluster: str, nodes: int, start: int = 0, end: int = 10, flexible: bool = False) -> ReservationRequest:
    return ReservationRequest(i, f"c{i}", "standard", cluster, flexible, nodes, start, end)


def test_ledger_holds_releases_and_moves() -> None:
    led = CapacityLedger(CL, 20, 1.0)
    led.hold(1, "n-h200", 6, 0, 10)
    assert not led.fits("n-h200", 5, 15, 5)
    led.release_from(1, 5)
    assert led.fits("n-h200", 5, 15, 10) and not led.fits("n-h200", 0, 5, 5)
    led.move(1, "w-h200")
    assert led.fits("n-h200", 0, 20, 10)
    led.check()


def test_flexible_request_goes_to_the_same_gpu_elsewhere_only_with_rebalancing() -> None:
    led = CapacityLedger(CL, 20, 1.0)
    led.hold(1, "n-h200", 8, 0, 10)
    r = req(2, "n-h200", 5, flexible=True)
    assert place(r, led, {}, rebalance=False).cluster is None
    assert place(r, led, {}, rebalance=True).cluster == "w-h200"
    assert place(req(3, "n-b200", 11), led, {}, rebalance=True).cluster is None  # never another GPU type


def test_rebalancing_moves_a_pending_flexible_reservation_or_nothing() -> None:
    led = CapacityLedger(CL, 20, 1.0)
    pend = req(1, "n-h200", 6, 5, 15, flexible=True)
    led.hold(1, "n-h200", 6, 5, 15)
    led.hold(9, "w-h200", 2, 0, 20)
    p = place(req(2, "n-h200", 8, 0, 10), led, {1: pend}, rebalance=True)
    assert p.cluster == "n-h200" and p.moved == [(1, "n-h200", "w-h200")]
    led2 = CapacityLedger(CL, 20, 1.0)
    led2.hold(1, "n-h200", 6, 5, 15)
    led2.hold(9, "w-h200", 9, 0, 20)  # no room elsewhere: nothing moves
    assert place(req(2, "n-h200", 8, 0, 10), led2, {1: pend}, rebalance=True).cluster is None
    assert led2.holds[1][0] == "n-h200"


def test_buffered_lending_keeps_room_for_a_daily_peak() -> None:
    spd = 8
    day = [2, 2, 2, 9, 9, 9, 2, 2]
    naive = Lender(10, "naive", spd, 4, 100, 0.999, 1)
    buff = Lender(10, "buffered", spd, 8, 100, 0.999, 1)
    short = {"naive": 0, "buffered": 0}
    for _day in range(4):
        for u in day:
            for name, lender in (("naive", naive), ("buffered", buff)):
                lent = lender.lend()
                short[name] += max(0, u - (10 - lent))
                lender.observe(u)
    assert short["naive"] > 0
    assert short["buffered"] < short["naive"]


def test_lending_off_lends_nothing() -> None:
    lender = Lender(10, "off", 4, 0, 10, 0.99, 1)
    for _ in range(10):
        assert lender.lend() == 0
        lender.observe(1)


def test_water_fill_is_max_min_fair_and_never_over_asks() -> None:
    asks = np.array([1, 5, 10, 10])
    got = water_fill(asks, np.ones(4), 16)
    assert got.sum() == 16 and (got <= asks).all()
    assert got[0] == 1 and got[1] == 5 and abs(int(got[2]) - int(got[3])) <= 1
    assert water_fill(asks, np.ones(4), 100).tolist() == asks.tolist()
    heavy = water_fill(np.array([10, 10]), np.array([2.0, 1.0]), 9)
    assert heavy[0] == 6 and heavy[1] == 3


def test_fifo_serves_the_first_in_full() -> None:
    assert fifo(np.array([5, 5, 5]), np.array([2, 0, 1]), 7).tolist() == [2, 0, 5]


def test_jain() -> None:
    assert jain(np.array([1.0, 1.0, 1.0])) == pytest.approx(1.0)
    assert jain(np.array([1.0, 0.0, 0.0, 0.0])) == pytest.approx(0.25)


W = {"new_account": 0.35, "payment_unverified": 0.3, "no_prior_spend": 0.2, "single_member": 0.1, "big_jump": 0.15, "flat_out": 0.35}
CFG = {"auto_approve_max_nodes": 16, "auto_approve_risk_max": 0.3, "risk_weights": W}
GOOD = {"account_age_days": 400.0, "payment_verified": 1.0, "prior_spend_eur": 900.0, "team_members": 6.0}


def test_quota_routing() -> None:
    assert route(QuotaAsk(1, 1, "s", 2, 6, GOOD), "scored", CFG) == "approve"
    assert route(QuotaAsk(1, 1, "s", 2, 20, GOOD), "scored", CFG) == "review"  # big asks always see a person
    shady = {**GOOD, "account_age_days": 2.0, "payment_verified": 0.0}
    assert risk(QuotaAsk(1, 1, "s", 2, 6, shady), W) > 0.3
    assert route(QuotaAsk(1, 1, "s", 2, 6, shady), "scored", CFG) == "review"
    mining = {**GOOD, "at_quota_share_24h": 1.0}
    assert route(QuotaAsk(1, 1, "s", 2, 6, mining), "scored", CFG) == "review"
    assert route(QuotaAsk(1, 1, "s", 2, 6, GOOD), "manual", CFG) == "review"


def test_review_queue_works_in_order_within_capacity() -> None:
    q = ReviewQueue(20, 30)
    for i in range(3):
        q.push(QuotaAsk(i, i, "s", 1, 2, GOOD), 0)
    assert [a.id for a, _ in q.work()] == [0]
    assert [a.id for a, _ in q.work()] == [1, 2]  # 10 minutes left over + 30 = two reviews
    assert not q.queue


def test_lifecycle_refuses_illegal_moves() -> None:
    assert advance(State.CONFIRMED, State.ACTIVE) == State.ACTIVE
    with pytest.raises(IllegalTransition):
        advance(State.RECLAIMED, State.ACTIVE)
    with pytest.raises(IllegalTransition):
        advance(State.REQUESTED, State.ACTIVE)
