from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gqc.service.app import create_app

GOOD = {"account_age_days": 400, "payment_verified": 1, "prior_spend_eur": 900, "team_members": 6}


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    c = TestClient(create_app(str(tmp_path / "gqc.sqlite3")))
    assert c.put("/v1/capacity/eu-north1-h200", json={"nodes": 10}).status_code == 200
    assert c.put("/v1/quotas/acme/eu-north1-h200", json={"nodes": 8}).status_code == 200
    return c


def test_health(api: TestClient) -> None:
    assert api.get("/healthz").json() == {"status": "ok"}


def test_reserve_is_confirmed_and_counted(api: TestClient) -> None:
    r = api.post("/v1/reservations", json={"org": "acme", "cluster": "eu-north1-h200", "nodes": 4}, headers={"Idempotency-Key": "order-0001"})
    assert r.status_code == 201 and r.json()["state"] == "confirmed"
    assert api.get("/v1/capacity").json() == [{"cluster": "eu-north1-h200", "total": 10, "free": 6, "held": 4}]
    assert api.get("/v1/quotas/acme").json()[0]["used"] == 4
    assert api.get(f"/v1/reservations/{r.json()['id']}").json()["state"] == "confirmed"


def test_a_replay_returns_the_same_reservation(api: TestClient) -> None:
    body = {"org": "acme", "cluster": "eu-north1-h200", "nodes": 4}
    a = api.post("/v1/reservations", json=body, headers={"Idempotency-Key": "order-0002"}).json()
    b = api.post("/v1/reservations", json=body, headers={"Idempotency-Key": "order-0002"}).json()
    assert a["id"] == b["id"]
    assert api.get("/v1/capacity").json()[0]["held"] == 4


def test_a_key_reused_for_another_request_is_refused(api: TestClient) -> None:
    api.post("/v1/reservations", json={"org": "acme", "cluster": "eu-north1-h200", "nodes": 4}, headers={"Idempotency-Key": "order-0003"})
    r = api.post("/v1/reservations", json={"org": "acme", "cluster": "eu-north1-h200", "nodes": 2}, headers={"Idempotency-Key": "order-0003"})
    assert r.status_code == 422


def test_over_quota_is_rejected_and_capacity_returned(api: TestClient) -> None:
    r = api.post("/v1/reservations", json={"org": "acme", "cluster": "eu-north1-h200", "nodes": 9}, headers={"Idempotency-Key": "order-0004"})
    assert r.json()["state"] == "rejected" and r.json()["reason"] == "over quota"
    assert api.get("/v1/capacity").json()[0]["free"] == 10


def test_missing_key_unknown_cluster_and_bad_input(api: TestClient) -> None:
    body = {"org": "acme", "cluster": "eu-north1-h200", "nodes": 1}
    assert api.post("/v1/reservations", json=body).status_code == 422
    assert api.post("/v1/reservations", json={**body, "cluster": "mars-1"}, headers={"Idempotency-Key": "order-0005"}).status_code == 404
    assert api.post("/v1/reservations", json={**body, "nodes": 0}, headers={"Idempotency-Key": "order-0006"}).status_code == 422
    assert api.put("/v1/capacity/eu-north1-h200", json={"nodes": -1}).status_code == 422


def test_capacity_and_quota_cannot_shrink_below_use(api: TestClient) -> None:
    api.post("/v1/reservations", json={"org": "acme", "cluster": "eu-north1-h200", "nodes": 6}, headers={"Idempotency-Key": "order-0007"})
    assert api.put("/v1/capacity/eu-north1-h200", json={"nodes": 4}).status_code == 409
    assert api.put("/v1/quotas/acme/eu-north1-h200", json={"nodes": 5}).status_code == 409


def test_quota_requests_are_scored(api: TestClient) -> None:
    ok = api.post("/v1/quota-requests", json={"org": "acme", "service": "eu-north1-h200", "asked": 12, "signals": GOOD}).json()
    assert ok["decision"] == "approved" and ok["limit"] == 12
    shady = {**GOOD, "account_age_days": 1, "payment_verified": 0}
    rv = api.post("/v1/quota-requests", json={"org": "newco", "service": "eu-north1-h200", "asked": 4, "signals": shady}).json()
    assert rv["decision"] == "review"
    assert api.post("/v1/quota-requests", json={"org": "acme", "service": "x", "asked": 4, "signals": {}}).status_code == 422


def test_a_restart_finishes_what_a_crash_left(tmp_path: Path) -> None:
    from gqc.platform.saga import ControlPlane, drive
    from gqc.platform.store import SQLiteStore

    db = tmp_path / "crash.sqlite3"
    store = SQLiteStore(db)
    cp = ControlPlane(store, lambda: "res-crashed", lambda m: None)
    cp.set_capacity("c", 10)
    cp.set_quota("acme", "c", 8)
    drive(cp.create_reservation("acme:k", "acme", "c", 3))  # committed with its outbox row, then the process "dies"
    api = TestClient(create_app(str(db)))
    assert api.get("/v1/reservations/res-crashed").json()["state"] == "confirmed"
