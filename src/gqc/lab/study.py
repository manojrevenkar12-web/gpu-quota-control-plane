"""The study: every design on the same sites, the crash and concurrency lab, and the release gates. The held-out
sites and scenarios run once, behind reports/heldout.lock (ADR 0006)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..sim.evaluate import run_design
from ..world.world import build_site
from .faults import run_faults

REPORTS = config.REPORTS
LOCK = REPORTS / "heldout.lock"
PER_SEED = ("gpu_utilisation", "reservations_rejected", "sla_short_share", "revenue", "quota_decision_p90_h", "jain_contested")


class HeldOutLocked(RuntimeError):
    pass


def config_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(config.CONFIG.rglob("*.yml")):
        h.update(p.read_bytes())
    return h.hexdigest()


def _round(x: Any) -> Any:
    if isinstance(x, (float, np.floating)):
        return round(float(x), 5)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def _mean(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {k: float(np.mean([r.get(k, 0.0) for r in rows])) for k in sorted(set().union(*rows))}


def check_gates(res: dict[str, Any]) -> dict[str, Any]:
    g = config.gates()
    gp, gf = g["platform"], g["faults"]
    p, a = res["designs"]["platform"], res["designs"]["as_is"]
    rows = [
        ("GPU utilisation over the as-is, points", 100 * (p["gpu_utilisation"] - a["gpu_utilisation"]), gp["utilisation_over_as_is_pts_min"], "min"),
        ("Reservation requests turned away, ratio to the as-is", p["reservations_rejected"] / max(a["reservations_rejected"], 1e-9), gp["rejected_vs_as_is_max"], "max"),
        ("Reserved use that was there when the customer needed it", 1 - p["sla_short_share"], gp["reserved_use_met_min"], "min"),
        ("Customers who came back to a released reservation, per site", p["wrongful_reclaims"], gp["wrongful_reclaims_max"], "max"),
        ("Revenue, ratio to the as-is", p["revenue"] / a["revenue"], gp["revenue_vs_as_is_min"], "min"),
        ("Quota increases granted to abusive organisations, ratio to the as-is", (p["abusive_approved"] + 1) / (a["abusive_approved"] + 1), gp["abusive_approved_vs_as_is_max"], "max"),
        ("Quota decision time, p90 hours", p["quota_decision_p90_h"], gp["quota_decision_p90_hours_max"], "max"),
        ("Fairness on contested capacity (Jain)", p["jain_contested"], gp["jain_contested_min"], "min"),
    ]
    f = res["faults"]["variants"]
    rows.append(("Lab scenarios with a broken invariant, full saga", f["platform"]["scenarios_broken"], gf["platform_scenarios_broken_max"], "max"))
    if gf["each_safeguard_matters"]:
        weakest = min(v["scenarios_broken"] for k, v in f.items() if k != "platform")
        rows.append(("Fewest broken scenarios with one safeguard removed", weakest, 1, "min"))
    out = [{"gate": n, "value": float(v), "limit": float(lim), "kind": k, "pass": bool(v <= lim if k == "max" else v >= lim)} for n, v, lim, k in rows]
    return {"platform": out, "platform_pass": all(r["pass"] for r in out)}


def run_split(split: str) -> dict[str, Any]:
    seeds = [int(s) for s in config.seeds()[split]]
    variant = "heldout" if split == "heldout" else "dev"
    dcfg = config.designs()
    cfg = config.platform()
    per: dict[str, list[dict[str, Any]]] = {n: [] for n in dcfg["designs"]}
    sites = []
    for s in seeds:
        site = build_site(s, variant)
        sites.append({"seed": s, "reservations": len(site.reservations), "requests": len(site.requests), "orgs": len(site.orgs), "nodes": sum(c.nodes for c in site.clusters.values())})
        for n, d in dcfg["designs"].items():
            per[n].append(run_design(site, d["switches"], cfg))
    nf = int(config.seeds()["faults_heldout" if split == "heldout" else "faults_dev"])
    res: dict[str, Any] = {
        "split": split,
        "seeds": seeds,
        "labels": {n: d["label"] for n, d in dcfg["designs"].items()},
        "main": dcfg["main"],
        "ablations": dcfg["ablations"],
        "designs": {n: _mean(rows) for n, rows in per.items()},
        "per_seed": [{"seed": s, **{n: {k: per[n][i][k] for k in PER_SEED} for n in dcfg["main"]}} for i, s in enumerate(seeds)],
        "sites": sites,
        "days": int(build_site(seeds[0], variant).cfg["days"]),
        "faults": run_faults(nf, 7 if split == "heldout" else 1),
    }
    res["gates"] = check_gates(res)
    return _round(res)


def write(split: str, res: dict[str, Any]) -> Path:
    REPORTS.mkdir(exist_ok=True)
    p = REPORTS / f"{split}.json"
    p.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return p


def run_heldout_once() -> dict[str, Any]:
    if LOCK.exists():
        raise HeldOutLocked(f"{LOCK} exists: the held-out sites have been run. Add new seeds under a new name and an ADR.")
    REPORTS.mkdir(exist_ok=True)
    LOCK.write_text(json.dumps({"seeds": config.seeds()["heldout"], "config_sha256": config_hash()}, indent=1) + "\n", encoding="utf-8")
    res = run_split("heldout")
    write("heldout", res)
    return res
