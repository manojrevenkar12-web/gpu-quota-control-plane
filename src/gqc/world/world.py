"""The GPU cloud as it really is: reservations and how much of them customers use, self-serve organisations and
what they would run, quota requests and which of them are abusive. Keyed randomness: every design sees the same
customers, the same usage and the same reviewer luck.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import Any

import numpy as np
import yaml

from ..config import CONFIG
from ..rng import keyed

WORLD = CONFIG / "world.yml"


@cache
def _world() -> dict[str, Any]:
    data = yaml.safe_load(WORLD.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def world_cfg(variant: str) -> dict[str, Any]:
    return dict(_world()[variant])


@dataclass
class Cluster:
    name: str
    region: str
    gpu: str
    nodes: int


@dataclass
class Reservation:
    id: int
    customer: str
    tier: str
    cluster: str
    flexible: bool
    nodes: int
    request_step: int
    start: int
    end: int
    profile: str
    usage: np.ndarray  # nodes in use per step over [start, end): the truth, revealed one step at a time


@dataclass
class Org:
    id: int
    cluster: str
    abusive: bool
    quota: int  # nodes at the start
    demand: np.ndarray  # nodes it would run per step if allowed
    signals: dict[str, float]


@dataclass
class QuotaRequest:
    id: int
    org: int
    step: int
    nodes: int  # the quota asked for


@dataclass
class Site:
    seed: int
    variant: str
    cfg: dict[str, Any]
    steps: int
    clusters: dict[str, Cluster]
    reservations: list[Reservation]
    orgs: list[Org]
    requests: list[QuotaRequest]
    _luck: dict[tuple[object, ...], float] = field(default_factory=dict)

    def luck(self, *key: object) -> float:
        if key not in self._luck:
            self._luck[key] = float(keyed(self.seed, "luck", *key).random())
        return self._luck[key]

    @property
    def steps_per_day(self) -> int:
        return int(24 * 60 / int(self.cfg["step_minutes"]))


def _usage(r: np.random.Generator, profile: str, nodes: int, length: int, spd: int, late: tuple[int, int]) -> np.ndarray:
    t = np.arange(length)
    hour = (t % spd) / spd * 24
    if profile == "never":
        u = np.zeros(length)
    elif profile == "steady":
        u = nodes * np.clip(r.normal(0.93, 0.04, length), 0, 1)
    elif profile == "diurnal":
        day = (hour >= 7) & (hour < 21)
        weekend = ((t // spd) % 7) >= 5
        u = nodes * np.where(day & ~weekend, 0.95, np.where(weekend, 0.15, 0.30)) + r.normal(0, 0.3, length)
    elif profile == "bursty":
        u = np.full(length, 0.25 * nodes)
        k = 0
        while k < length:
            gap = int(r.exponential(spd * 0.8))
            k += gap
            dur = int(r.integers(spd // 6, spd // 2))
            u[k : k + dur] = nodes
            k += dur
    elif profile == "late":
        delay = int(r.integers(late[0] * spd, late[1] * spd))
        u = np.where(t >= delay, nodes * 0.9, 0.0)
    else:  # ramp
        u = nodes * np.clip(0.1 + 0.9 * t / max(length * 0.6, 1), 0, 1)
    return np.clip(np.round(u), 0, nodes).astype(int)


def build_site(seed: int, variant: str = "dev") -> Site:
    cfg = world_cfg(variant)
    spd = int(24 * 60 / int(cfg["step_minutes"]))
    steps = int(cfg["days"]) * spd
    clusters = {k: Cluster(k, v["region"], v["gpu"], int(v["nodes"])) for k, v in cfg["clusters"].items()}
    rc = cfg["reservations"]
    names = list(clusters)
    weights = np.array([clusters[c].nodes for c in names], dtype=float)
    tiers = list(rc["tiers"])
    tp = np.array([rc["tiers"][x] for x in tiers])
    profiles = list(rc["profiles"])
    pp = np.array([rc["profiles"][x] for x in profiles])
    reservations = []
    for i in range(int(rc["count"])):
        ri = keyed(seed, "reservation", i)
        nodes = int(np.clip(round(ri.lognormal(*rc["nodes_lognormal"])), 1, 40))
        request = int(ri.integers(0, int(rc["arrive_within_days"]) * spd))
        start = request + int(ri.integers(0, spd))
        dur = int(ri.integers(int(rc["duration_days"][0]) * spd, int(rc["duration_days"][1]) * spd + 1))
        end = min(steps, start + dur)
        if end <= start:
            continue
        never = ri.random() < float(rc["never_used_share"])
        late = (not never) and ri.random() < 0.06
        profile = "never" if never else "late" if late else str(ri.choice(profiles, p=pp))
        reservations.append(
            Reservation(
                i,
                f"customer-{i:03d}",
                str(ri.choice(tiers, p=tp)),
                str(ri.choice(names, p=weights / weights.sum())),
                bool(ri.random() < float(rc["region_flexible_share"])),
                nodes,
                request,
                start,
                end,
                profile,
                _usage(ri, profile, nodes, end - start, spd, (int(cfg["late_start_days"][0]), int(cfg["late_start_days"][1]))),
            )
        )
    oc = cfg["ondemand"]
    orgs = []
    for j in range(int(oc["orgs"])):
        rj = keyed(seed, "org", j)
        abusive = bool(rj.random() < float(oc["abusive_share"]))
        cluster = str(rj.choice(names, p=weights / weights.sum()))
        peak = max(1, round(float(rj.lognormal(*oc["demand_nodes_lognormal"]))))
        t = np.arange(steps)
        hour = (t % spd) / spd * 24
        if abusive:
            peak = max(peak, int(rj.integers(4, 12)))
            d = np.full(steps, peak)
        else:
            on = (hour >= rj.uniform(6, 10)) & (hour < rj.uniform(17, 23))
            d = np.where(on, peak, np.round(peak * rj.uniform(0, 0.5))).astype(int)
            d = np.where(rj.random(steps) < 0.03, 0, d)
        signals = {  # abusive organisations mostly look new and thin; some do not
            "account_age_days": float(rj.integers(0, 14) if abusive and rj.random() < 0.6 else rj.integers(3, 900)),
            "payment_verified": float(rj.random() < (0.5 if abusive else 0.92)),
            "prior_spend_eur": float(0 if (abusive and rj.random() < 0.55) or rj.random() < 0.08 else round(rj.lognormal(7, 1.2))),
            "team_members": float(1 if (abusive and rj.random() < 0.5) or rj.random() < 0.2 else rj.integers(2, 30)),
        }
        orgs.append(Org(j, cluster, abusive, int(rj.integers(1, 3)), d.astype(int), signals))
    requests: list[QuotaRequest] = []
    rq = keyed(seed, "requests")
    n_req = int(oc["requests_per_day"]) * int(cfg["days"])
    asked: set[int] = set()
    k = 0
    while len(requests) < n_req and k < n_req * 5:
        k += 1
        o = orgs[int(rq.integers(0, len(orgs)))]
        if o.id in asked and rq.random() < 0.8:
            continue
        asked.add(o.id)
        want = int(o.demand.max()) + (int(rq.integers(0, 3)) if not o.abusive else int(rq.integers(2, 10)))
        if want <= o.quota:
            continue
        requests.append(QuotaRequest(len(requests), o.id, int(rq.integers(0, steps - spd)), want))
    requests.sort(key=lambda q: (q.step, q.id))
    requests = [QuotaRequest(i, q.org, q.step, q.nodes) for i, q in enumerate(requests)]
    return Site(seed, variant, cfg, steps, clusters, reservations, orgs, requests)


def keeps_after_notice(site: Site, r: Reservation) -> bool:
    """Whether the customer answers a reclaim notice with "keep it". Customers who mean to use it mostly do."""
    p = site.cfg["notice_keep_prob"]["never_uses" if r.profile == "never" else "intends_to_use"]
    return site.luck("notice", r.id) < float(p)


def reviewer_right(site: Site, q: QuotaRequest) -> bool:
    """Whether the analyst who reviews this request gets it right. Same luck for every design."""
    return site.luck("review", q.id) < float(site.cfg["review"]["accuracy"])
