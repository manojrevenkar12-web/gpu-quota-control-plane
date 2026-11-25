"""One design on one site, step by step: reservations arrive and are placed, customers use them (the truth is
revealed one step at a time), idle nodes are lent and taken back, unused reservations are noticed and reclaimed,
self-serve organisations share what is left within their quotas, and quota requests are decided."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

from .. import config
from ..domain import Cluster, QuotaAsk, ReservationRequest, State, advance
from ..platform.fairness import fifo, jain, water_fill
from ..platform.ledger import CapacityLedger
from ..platform.lending import Lender
from ..platform.placement import place
from ..platform.quotas import ReviewQueue, route
from ..platform.reclaim import ReclaimClock
from ..rng import keyed
from ..world.world import Site, keeps_after_notice, reviewer_right

METRICS = (
    "abusive_approved",
    "abusive_requests",
    "abusive_served_node_h",
    "auto_decisions",
    "capacity_node_h",
    "contested_steps",
    "idle_reserved_node_h",
    "legit_capped_by_quota_node_h",
    "legit_demand_node_h",
    "legit_denied",
    "legit_requests",
    "legit_served_node_h",
    "lent_node_h",
    "moved_to_make_room",
    "moved_to_other_region",
    "notices_sent",
    "ondemand_served_node_h",
    "preempted_node_h",
    "quota_decisions",
    "reclaimed",
    "reclaimed_never_used",
    "reclaimed_node_h",
    "rejected_strategic",
    "reservations_rejected",
    "reservations_requested",
    "reserved_live_node_h",
    "reserved_node_h_rejected",
    "reserved_node_h_requested",
    "reserved_used_node_h",
    "revenue_ondemand",
    "revenue_reserved",
    "sla_short_node_h",
    "sla_short_steps",
    "unpaid_node_h",
    "wrongful_reclaim_node_h",
    "wrongful_reclaims",
)


def _office(step: int, spd: int) -> bool:
    hour = (step % spd) / spd * 24
    return (step // spd) % 7 < 5 and 9 <= hour < 17


def run_design(site: Site, sw: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or config.platform()
    spd, steps = site.steps_per_day, site.steps
    hours = int(site.cfg["step_minutes"]) / 60
    prices = site.cfg["prices_per_node_hour"]
    clusters = {k: Cluster(c.name, c.region, c.gpu, c.nodes) for k, c in site.clusters.items()}
    ledger = CapacityLedger(clusters, steps, float(cfg["reservations"]["reservable_share"]))
    lc = cfg["lending"]
    rc = cfg["reclaim"]
    clock = ReclaimClock(int(rc["grace_hours"] / hours), int(rc["notice_hours"] / hours))
    res = {r.id: r for r in site.reservations}
    arrivals: dict[int, list[int]] = defaultdict(list)
    for r in site.reservations:
        arrivals[r.request_step].append(r.id)
    req: dict[int, ReservationRequest] = {}
    state: dict[int, State] = {}
    lender: dict[int, Lender] = {}
    used: dict[int, int] = defaultdict(int)
    noticed_at: dict[int, int] = {}
    kept: set[int] = set()
    activated: set[int] = set()
    reclaimed_at: dict[int, int] = {}
    last_lent: dict[int, int] = defaultdict(int)
    m: dict[str, float] = dict.fromkeys(METRICS, 0.0)
    short_res: set[int] = set()

    orgs = site.orgs
    quota = np.array([o.quota for o in orgs])
    abusive = np.array([o.abusive for o in orgs])
    weight = np.array([cfg["fairness"]["weight"]["paying" if o.signals["payment_verified"] > 0.5 else "unverified"] for o in orgs])
    by_cluster = {c: np.array([o.id for o in orgs if o.cluster == c], dtype=int) for c in clusters}
    arrival_order = keyed(site.seed, "fifo-order").permutation(len(orgs))
    rank = np.empty(len(orgs), dtype=int)
    rank[arrival_order] = np.arange(len(orgs))
    demand = np.stack([o.demand for o in orgs])
    at_quota = np.zeros((len(orgs), steps), dtype=bool)  # metering: launches that hit the quota, as the plane sees them
    asks_at: dict[int, list[int]] = defaultdict(list)
    for q in site.requests:
        asks_at[q.step].append(q.id)
    rv = site.cfg["review"]
    queue = ReviewQueue(float(rv["minutes"]), float(rv["analysts_minutes_per_day"]) / (8 * spd / 24))
    decided_h: list[float] = []
    legit_wait_node_h = 0.0
    jains: list[float] = []

    def decide(qid: int, approve: bool, step_asked: int, step: int) -> None:
        nonlocal legit_wait_node_h
        q = site.requests[qid]
        o = orgs[q.org]
        decided_h.append((step - step_asked) * hours)
        if approve:
            quota[q.org] = max(quota[q.org], q.nodes)
            m["abusive_approved"] += o.abusive
        else:
            m["legit_denied"] += not o.abusive
        m["quota_decisions"] += 1
        m["abusive_requests"] += o.abusive
        m["legit_requests"] += not o.abusive

    for t in range(steps):
        # reservations arriving now
        for rid in arrivals.get(t, []):
            r = res[rid]
            rq = ReservationRequest(r.id, r.customer, r.tier, r.cluster, r.flexible, r.nodes, r.start, r.end)
            pending = {i: req[i] for i, s in state.items() if s == State.CONFIRMED and req[i].start > t}
            p = place(rq, ledger, pending, bool(sw["rebalance"]))
            m["reservations_requested"] += 1
            m["reserved_node_h_requested"] += r.nodes * (r.end - r.start) * hours
            if p.cluster is None:
                state[rid] = advance(State.REQUESTED, State.REJECTED)
                m["reservations_rejected"] += 1
                m["reserved_node_h_rejected"] += r.nodes * (r.end - r.start) * hours
                m["rejected_strategic"] += r.tier == "strategic"
                continue
            ledger.hold(rid, p.cluster, r.nodes, r.start, r.end)
            req[rid] = rq
            state[rid] = advance(State.REQUESTED, State.CONFIRMED)
            m["moved_to_other_region"] += p.cluster != r.cluster
            m["moved_to_make_room"] += len(p.moved)
            lender[rid] = Lender(r.nodes, str(sw["lending"]), spd, int(lc["warmup_steps"]), int(lc["window_steps"]), float(lc["error_quantile"]), int(lc["min_buffer_nodes"]))

        # reservations live at this step
        occupied: dict[str, int] = defaultdict(int)
        for rid, s in list(state.items()):
            if s in (State.REJECTED, State.EXPIRED):
                continue
            r = res[rid]
            if t < r.start:
                continue
            if t >= r.end:
                if s != State.RECLAIMED:
                    state[rid] = advance(State.ACTIVE if s == State.ACTIVE else s, State.EXPIRED) if s != State.ACTIVE else advance(s, State.EXPIRED)
                else:
                    state[rid] = State.RECLAIMED
                continue
            u = int(r.usage[t - r.start])
            if s == State.RECLAIMED:
                if u > 0:  # the customer came back to nothing
                    m["sla_short_node_h"] += u * hours
                    m["wrongful_reclaim_node_h"] += u * hours
                    short_res.add(rid)
                    if rid not in kept:
                        kept.add(rid)
                        m["wrongful_reclaims"] += 1
                continue
            if u > 0 and s in (State.CONFIRMED, State.NOTICED):
                s = state[rid] = advance(s, State.ACTIVE)
                activated.add(rid)
            if sw["reclaim_unused"] and rid not in kept:
                act = clock.due(s, r.start, t, used[rid], noticed_at.get(rid))
                if act == "notice":
                    s = state[rid] = advance(s, State.NOTICED)
                    noticed_at[rid] = t
                    m["notices_sent"] += 1
                    if keeps_after_notice(site, r):
                        s = state[rid] = advance(s, State.CONFIRMED)
                        kept.add(rid)
                elif act == "reclaim":
                    ledger.release_from(rid, t)
                    s = state[rid] = advance(s, State.RECLAIMED)
                    reclaimed_at[rid] = t
                    m["reclaimed"] += 1
                    m["reclaimed_node_h"] += r.nodes * (r.end - t) * hours
                    m["reclaimed_never_used"] += r.profile == "never"
                    if u > 0:
                        m["sla_short_node_h"] += u * hours
                    continue
            lent = lender[rid].lend()
            short = max(0, u - (r.nodes - lent))
            lender[rid].observe(u)
            used[rid] += u
            cluster = ledger.holds[rid][0]
            occupied[cluster] += r.nodes - lent
            m["reserved_used_node_h"] += u * hours
            m["reserved_live_node_h"] += r.nodes * hours
            m["lent_node_h"] += lent * hours
            m["idle_reserved_node_h"] += max(0, r.nodes - u - lent) * hours
            m["preempted_node_h"] += max(0, last_lent[rid] - lent) * hours
            last_lent[rid] = lent
            if short:
                m["sla_short_node_h"] += short * hours
                m["sla_short_steps"] += 1
                short_res.add(rid)
            if s == State.ACTIVE:
                m["revenue_reserved"] += r.nodes * hours * float(prices["reserved"])

        # self-serve organisations on what is left
        for c, ids in by_cluster.items():
            if len(ids) == 0:
                continue
            pool = clusters[c].nodes - occupied[c]
            want = np.minimum(demand[ids, t], quota[ids])
            at_quota[ids, t] = demand[ids, t] >= quota[ids]
            fair = sw["allocation"] == "fair"
            got = water_fill(want, weight[ids], pool) if fair else fifo(want, np.argsort(rank[ids], kind="stable"), pool)
            leg = ~abusive[ids]
            m["ondemand_served_node_h"] += got.sum() * hours
            m["legit_demand_node_h"] += demand[ids, t][leg].sum() * hours
            m["legit_served_node_h"] += got[leg].sum() * hours
            m["legit_capped_by_quota_node_h"] += (demand[ids, t] - want)[leg].sum() * hours
            m["abusive_served_node_h"] += got[~leg].sum() * hours
            if want.sum() > pool:
                m["contested_steps"] += 1
                w = want[leg]
                if (w > 0).sum() > 1:
                    jains.append(jain(got[leg][w > 0] / w[w > 0]))
            pay = np.where(abusive[ids], 1 - float(site.cfg["ondemand"]["abusive_unpaid_share"]), 1.0)
            m["revenue_ondemand"] += float((got * pay).sum()) * hours * float(prices["ondemand"])
            m["unpaid_node_h"] += float((got * (1 - pay)).sum()) * hours
            m["capacity_node_h"] += clusters[c].nodes * hours

        # quota requests
        for qid in asks_at.get(t, []):
            q = site.requests[qid]
            o = orgs[q.org]
            seen = at_quota[q.org, max(0, t - spd) : t]
            signals = {**o.signals, "at_quota_share_24h": float(seen.mean()) if len(seen) else 0.0}
            ask = QuotaAsk(q.id, q.org, o.cluster, int(quota[q.org]), q.nodes, signals)
            if route(ask, str(sw["quotas"]), cfg["quotas"]) == "approve":
                decide(qid, True, t, t)
                m["auto_decisions"] += 1
            else:
                queue.push(ask, t)
        if _office(t, spd):
            for ask, asked_at in queue.work():
                o = orgs[ask.org]
                right = reviewer_right(site, site.requests[ask.id])
                decide(ask.id, (not o.abusive) == right, asked_at, t)
        for ask, _ in queue.queue:
            if not orgs[ask.org].abusive:
                legit_wait_node_h += hours

    ledger.check()
    total_cap = sum(c.nodes for c in clusters.values()) * steps * hours
    out = dict(m)
    out.update(
        {
            "gpu_utilisation": (m["reserved_used_node_h"] + m["ondemand_served_node_h"]) / total_cap,
            "reservations_admitted": m["reservations_requested"] - m["reservations_rejected"],
            "reservations_short": len(short_res),
            "sla_short_share": m["sla_short_node_h"] / max(m["reserved_used_node_h"], 1e-9),
            "legit_served_share": m["legit_served_node_h"] / max(m["legit_demand_node_h"], 1e-9),
            "revenue": m["revenue_reserved"] + m["revenue_ondemand"],
            "quota_decision_p50_h": float(np.percentile(decided_h, 50)) if decided_h else 0.0,
            "quota_decision_p90_h": float(np.percentile(decided_h, 90)) if decided_h else 0.0,
            "auto_decision_rate": m["auto_decisions"] / max(m["quota_decisions"], 1),
            "legit_waiting_request_h": legit_wait_node_h,
            "jain_contested": float(np.mean(jains)) if jains else 1.0,
            "queue_left": len(queue.queue),
        }
    )
    return out
