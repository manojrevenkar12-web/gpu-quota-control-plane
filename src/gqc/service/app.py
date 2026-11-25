"""The reservation and quota API over the same saga the lab breaks. SQLite with optimistic concurrency; every
write runs the outbox relay and the consumers to completion before answering, and again at start-up, so a crash
between steps is finished on the next start."""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .. import config
from ..domain import QuotaAsk
from ..platform.quotas import risk, route
from ..platform.saga import ControlPlane, drive
from ..platform.store import SQLiteStore, Tx


class ReservationIn(BaseModel):
    org: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    cluster: str = Field(min_length=1, max_length=64)
    nodes: int = Field(ge=1, le=512)


class Limit(BaseModel):
    nodes: int = Field(ge=0, le=100_000)


class QuotaRequestIn(BaseModel):
    org: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    service: str = Field(min_length=1, max_length=64)
    asked: int = Field(ge=1, le=100_000)
    signals: dict[str, float]


def create_app(db_path: str | None = None) -> FastAPI:
    store = SQLiteStore(db_path or os.environ.get("GQC_DB", "gqc.sqlite3"))
    bus: list[dict[str, Any]] = []
    lock = threading.Lock()
    cp = ControlPlane(store, lambda: f"res-{uuid.uuid4().hex[:12]}", bus.append)
    qcfg = config.platform()["quotas"]
    app = FastAPI(title="GPU quota control plane", version="1.0.0")

    def settle() -> None:
        with lock:  # one settler at a time; correctness comes from the store, this only avoids wasted work
            for _ in range(100):
                sent = drive(cp.relay())
                if not sent and not bus:
                    return
                while bus:
                    drive(cp.handle(bus.pop(0)))

    settle()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.put("/v1/capacity/{cluster}")
    def put_capacity(cluster: str, body: Limit) -> dict[str, Any]:
        try:
            cp.set_capacity(cluster, body.nodes)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"cluster": cluster, **store.read("capacity", cluster)[1]}

    @app.get("/v1/capacity")
    def get_capacity() -> list[dict[str, Any]]:
        return [{"cluster": k, "total": v["total"], "free": v["free"], "held": sum(v["holds"].values())} for k, _, v in store.scan("capacity")]

    @app.put("/v1/quotas/{org}/{service}")
    def put_quota(org: str, service: str, body: Limit) -> dict[str, Any]:
        try:
            cp.set_quota(org, service, body.nodes)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"org": org, "service": service, **store.read("quota", f"{org}/{service}")[1]}

    @app.get("/v1/quotas/{org}")
    def get_quotas(org: str) -> list[dict[str, Any]]:
        return [{"service": k.split("/", 1)[1], **v} for k, _, v in store.scan("quota") if k.split("/", 1)[0] == org]

    @app.post("/v1/reservations", status_code=201)
    def post_reservation(body: ReservationIn, idempotency_key: str = Header(min_length=8, max_length=128)) -> dict[str, Any]:
        if store.read("capacity", body.cluster)[1] is None:
            raise HTTPException(404, f"unknown cluster {body.cluster}")
        rid = drive(cp.create_reservation(f"{body.org}:{idempotency_key}", body.org, body.cluster, body.nodes))
        settle()
        r = cp.reservation(rid)
        assert r is not None
        if (r["org"], r["cluster"], r["nodes"]) != (body.org, body.cluster, body.nodes):
            raise HTTPException(422, "this Idempotency-Key was used for a different request")
        return r

    @app.get("/v1/reservations/{rid}")
    def get_reservation(rid: str) -> dict[str, Any]:
        r = cp.reservation(rid)
        if r is None:
            raise HTTPException(404, "no such reservation")
        return r

    @app.post("/v1/quota-requests")
    def post_quota_request(body: QuotaRequestIn) -> dict[str, Any]:
        key = f"{body.org}/{body.service}"
        cur = store.read("quota", key)[1] or {"limit": 0, "used": 0}
        ask = QuotaAsk(0, 0, body.service, int(cur["limit"]), body.asked, body.signals)
        needed = {"account_age_days", "payment_verified", "prior_spend_eur", "team_members"}
        if not needed <= set(body.signals):
            raise HTTPException(422, f"signals must include {sorted(needed)}")
        decision = route(ask, "scored", qcfg)
        score = risk(ask, qcfg["risk_weights"])
        if decision == "approve":
            cp.set_quota(body.org, body.service, max(int(cur["limit"]), body.asked))
            return {"decision": "approved", "risk": score, "limit": max(int(cur["limit"]), body.asked)}
        tx = Tx(store)
        rq = f"q-{uuid.uuid4().hex[:12]}"
        tx.put("quota_requests", rq, {"org": body.org, "service": body.service, "asked": body.asked, "risk": score, "state": "review"})
        tx.commit()
        return {"decision": "review", "risk": score, "request": rq}

    return app
