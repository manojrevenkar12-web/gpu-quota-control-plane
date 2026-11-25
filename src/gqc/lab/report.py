"""Writes REPORT.md, the README results block and the console data from reports/*.json. Never edited by hand:
CI regenerates them and fails on a diff."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .. import config

ROOT = config.ROOT
START, END = "<!-- results:start -->", "<!-- results:end -->"
SHORT = {
    "as_is": "As found",
    "platform": "Control plane",
    "lend_naive": "Lend all idle",
    "no_lending": "No lending",
    "no_reclaim": "No reclaim",
    "no_rebalance": "No rebalancing",
    "manual_quotas": "Manual quotas",
    "auto_approve_all": "Approve all quotas",
    "fifo_allocation": "First come first served",
}
FAULT_LABEL = {
    "platform": "Full saga: version checks, Idempotency-Key, outbox, inbox",
    "no_cas": "Without version checks (last writer wins)",
    "no_idempotency": "Without the Idempotency-Key",
    "no_outbox": "Without the outbox (commit, then send)",
    "no_inbox": "Without the inbox (no de-duplication)",
}
KIND = {
    "oversold": "more promised than the cluster has",
    "unbacked": "confirmed with no capacity held",
    "duplicate": "two reservations for one request",
    "stuck": "never finished",
    "quota_drift": "quota usage wrong",
    "orphan_hold": "capacity held for a dead reservation",
    "capacity_drift": "free + held is not the total",
    "overheld": "holds above the total",
}


def _load(name: str) -> dict[str, Any] | None:
    p = config.REPORTS / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x: float | None, d: int = 1) -> str:
    return "–" if x is None else f"{100 * x:.{d}f}%"


def num(x: float | None, d: int = 0) -> str:
    return "–" if x is None else f"{x:,.{d}f}"


def eur(x: float | None) -> str:
    return "–" if x is None else f"€{x / 1000:,.0f}k"


Fmt = Callable[[float], str]
ROWS: list[tuple[str, str, Fmt]] = [
    ("**GPU utilisation** (node-hours doing work)", "gpu_utilisation", lambda x: pct(x, 1)),
    ("Reserved nodes sitting idle (node-hours)", "idle_reserved_node_h", num),
    ("Idle reserved nodes lent to preemptible jobs (node-hours)", "lent_node_h", num),
    ("Reservation requests turned away", "reservations_rejected", lambda x: num(x, 1)),
    ("Placed in another region of the same GPU type", "moved_to_other_region", lambda x: num(x, 1)),
    ("Reserved use there when the customer needed it", "sla_short_share", lambda x: pct(1 - x, 3)),
    ("Reservations short of nodes at least once", "reservations_short", lambda x: num(x, 1)),
    ("Unused reservations released after a notice", "reclaimed", lambda x: num(x, 1)),
    ("Customers who came back to a released reservation", "wrongful_reclaims", lambda x: num(x, 1)),
    ("Preemptible node-hours taken back for reservations", "preempted_node_h", num),
    ("Self-serve demand served", "legit_served_share", lambda x: pct(x, 1)),
    ("Fairness on contested capacity (Jain, 1 = equal)", "jain_contested", lambda x: num(x, 2)),
    ("Quota decision time, p90 (hours)", "quota_decision_p90_h", lambda x: num(x, 1)),
    ("Quota requests decided without a person", "auto_decision_rate", lambda x: pct(x, 0)),
    ("Quota increases granted to abusive organisations", "abusive_approved", lambda x: num(x, 1)),
    ("Legitimate quota requests denied", "legit_denied", lambda x: num(x, 1)),
    ("GPU node-hours nobody paid for", "unpaid_node_h", num),
    ("**Revenue** (placeholder prices)", "revenue", eur),
]


def _table(r: dict[str, Any], names: list[str], bold: str = "platform") -> list[str]:
    d = r["designs"]
    out = ["| | " + " | ".join(SHORT.get(n, n) for n in names) + " |", "|---|" + "---:|" * len(names)]
    for label, key, fmt in ROWS:
        cells = [fmt(d[n][key]) for n in names]
        if bold in names:
            i = names.index(bold)
            cells[i] = f"**{cells[i]}**"
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return out


def _faults(r: dict[str, Any]) -> list[str]:
    f = r["faults"]
    out = [f"| Saga variant ({f['scenarios']} scenarios each) | Scenarios with a broken invariant | What broke |", "|---|---:|---|"]
    for k, v in f["variants"].items():
        what = ", ".join(f"{KIND.get(x, x)} ({n})" for x, n in sorted(v["by_kind"].items(), key=lambda kv: -kv[1])) or "nothing"
        b = num(v["scenarios_broken"])
        out.append(f"| {FAULT_LABEL[k]} | {'**' + b + '**' if k == 'platform' else b} | {what} |")
    return out


def _gates(r: dict[str, Any]) -> list[str]:
    out = ["| Gate | Value | Limit | |", "|---|---:|---:|---|"]
    for g in r["gates"]["platform"]:
        out.append(f"| {g['gate']} | {g['value']:.4g} | {'≥' if g['kind'] == 'min' else '≤'} {g['limit']:g} | {'pass' if g['pass'] else '**FAIL**'} |")
    return out


def _per_seed(r: dict[str, Any]) -> list[str]:
    out = ["| Site | Utilisation (as found → plane) | Turned away | Reserved use met | Revenue |", "|---|---:|---:|---:|---:|"]
    for s in r["per_seed"]:
        a, p = s["as_is"], s["platform"]
        out.append(
            f"| {s['seed']} | {pct(a['gpu_utilisation'])} → **{pct(p['gpu_utilisation'])}** | {num(a['reservations_rejected'])} → **{num(p['reservations_rejected'])}** | {pct(1 - a['sla_short_share'], 2)} → **{pct(1 - p['sla_short_share'], 2)}** | {eur(a['revenue'])} → **{eur(p['revenue'])}** |"
        )
    return out


def _site_line(r: dict[str, Any]) -> str:
    s = r["sites"][0]
    return (
        f"{len(r['seeds'])} simulated sites of {r['days']} days, each {s['nodes']} nodes of 8 GPUs across six clusters, "
        f"about {s['reservations']} reservation requests and {s['orgs']} self-serve organisations. Numbers are the mean per site."
    )


def dashboard(dev: dict[str, Any], held: dict[str, Any] | None) -> list[str]:
    a, p = dev["designs"]["as_is"], dev["designs"]["platform"]
    fp = dev["faults"]["variants"]
    out = [
        "_Generated by `gqc report` from `reports/*.json`. Do not edit by hand._",
        "",
        _site_line(dev),
        "",
        "| | As found | Control plane |",
        "|---|---:|---:|",
        f"| GPU utilisation | {pct(a['gpu_utilisation'])} | **{pct(p['gpu_utilisation'])}** |",
        f"| Reserved nodes sitting idle (node-hours) | {num(a['idle_reserved_node_h'])} | **{num(p['idle_reserved_node_h'])}** |",
        f"| Reservation requests turned away | {num(a['reservations_rejected'], 1)} | **{num(p['reservations_rejected'], 1)}** |",
        f"| Reserved use there when the customer needed it | {pct(1 - a['sla_short_share'], 3)} | **{pct(1 - p['sla_short_share'], 3)}** |",
        f"| Quota decision time, p90 | {num(a['quota_decision_p90_h'], 1)} h | **{num(p['quota_decision_p90_h'], 1)} h** |",
        f"| Fairness on contested capacity (Jain) | {num(a['jain_contested'], 2)} | **{num(p['jain_contested'], 2)}** |",
        f"| Revenue per site (placeholder prices) | {eur(a['revenue'])} | **{eur(p['revenue'])}** |",
        f"| Crash-lab scenarios with a broken invariant | – | **{fp['platform']['scenarios_broken']} of {dev['faults']['scenarios']}** |",
        "",
    ]
    if held:
        ha, hp = held["designs"]["as_is"], held["designs"]["platform"]
        ok = sum(g["pass"] for g in held["gates"]["platform"])
        out += [
            f"**Held-out sites, run once** (burstier customers, more abuse): utilisation {pct(ha['gpu_utilisation'])} → **{pct(hp['gpu_utilisation'])}**, "
            f"turned away {num(ha['reservations_rejected'], 1)} → **{num(hp['reservations_rejected'], 1)}**, reserved use met **{pct(1 - hp['sla_short_share'], 3)}**, "
            f"crash lab **{held['faults']['variants']['platform']['scenarios_broken']} of {held['faults']['scenarios']}** broken; **{ok} of {len(held['gates']['platform'])} gates pass**.",
            "",
        ]
    return out


def report_md(dev: dict[str, Any], held: dict[str, Any] | None) -> str:
    out = ["# Report", "", "_Generated by `gqc report`. Do not edit by hand._", "", _site_line(dev), ""]
    out += ["## The control plane against the as-is and each ablation (development sites)", ""]
    out += _table(dev, dev["main"] + dev["ablations"]) + [""]
    out += ["What each design is:", ""] + [f"- **{SHORT.get(n, n)}**: {dev['labels'][n]}" for n in dev["main"] + dev["ablations"]] + [""]
    out += [
        "## Crash and concurrency lab",
        "",
        "Clients reserving one small cluster at once, retried requests, steps interleaved at random, workers crashed mid-step, messages delivered twice and out of order. Same scenarios for every variant.",
        "",
    ]
    out += _faults(dev) + [""]
    out += ["## Gates (development sites)", ""] + _gates(dev) + [""]
    out += ["## Per site", ""] + _per_seed(dev) + [""]
    if held:
        out += ["## Held-out sites (run once)", "", _site_line(held), ""]
        out += _table(held, held["main"] + held["ablations"]) + [""]
        out += _faults(held) + [""] + _gates(held) + [""] + _per_seed(held) + [""]
    return "\n".join(out)


def console_data(dev: dict[str, Any], held: dict[str, Any] | None) -> dict[str, Any]:
    keys = [k for _, k, _ in ROWS] + [
        "reserved_used_node_h",
        "ondemand_served_node_h",
        "abusive_served_node_h",
        "capacity_node_h",
        "reservations_requested",
        "quota_decision_p50_h",
        "sla_short_node_h",
    ]

    def pick(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "designs": {n: {k: r["designs"][n][k] for k in keys} for n in r["main"] + r["ablations"]},
            "labels": {n: SHORT.get(n, n) for n in r["main"] + r["ablations"]},
            "descriptions": r["labels"],
            "faults": r["faults"],
            "gates": r["gates"],
            "per_seed": r["per_seed"],
            "sites": r["sites"],
            "days": r["days"],
        }

    return {"dev": pick(dev), "heldout": pick(held) if held else None, "fault_labels": FAULT_LABEL, "fault_kinds": KIND}


def write_all() -> None:
    dev = _load("dev")
    if dev is None:
        raise SystemExit("reports/dev.json is missing: run `gqc dev` first")
    held = _load("heldout")
    (ROOT / "REPORT.md").write_text(report_md(dev, held), encoding="utf-8")
    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        if START in text and END in text:
            head, rest = text.split(START, 1)
            _, tail = rest.split(END, 1)
            readme.write_text(head + START + "\n" + "\n".join(dashboard(dev, held)) + "\n" + END + tail, encoding="utf-8")
    web = ROOT / "web" / "public" / "data"
    web.mkdir(parents=True, exist_ok=True)
    (web / "report.json").write_text(json.dumps(console_data(dev, held), indent=1) + "\n", encoding="utf-8")
