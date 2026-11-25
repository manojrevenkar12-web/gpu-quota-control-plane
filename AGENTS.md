# AGENTS.md

How to work in this repository, for people and coding agents alike.

## Fast feedback

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy src tests && pytest -q     # about 10 seconds
python -m gqc.cli dev && python -m gqc.cli gate dev                        # every design on the development sites, about a minute
cd web && npm ci && npm run typecheck && npm run lint && npm test          # the console
```

## Layout

| Package | Owns | May import |
|---|---|---|
| `gqc.world` | the simulated cloud and its hidden truth (`config/world.yml`) | `gqc.config`, `gqc.rng` |
| `gqc.platform` | the control plane: ledger, placement, lending, reclaim, quotas, fair share, store, saga | `gqc.config`, `gqc.domain` |
| `gqc.service` | the HTTP API over the saga | `gqc.platform` |
| `gqc.sim` | runs a design against the world and measures it against the truth | everything above |
| `gqc.lab` | the study, the crash and concurrency lab, the gates, the reports | everything above |
| `web/` | the console; reads only `web/public/data/report.json` | – |

## Invariants

1. **The truth stays in the world.** How much of a reservation a customer will use, whether they answer a notice,
   which organisation is abusive: only `gqc.world` knows. The platform sees one step of usage at a time, the
   signals on a request and its own metering. `tests/test_boundaries.py` fails if `gqc.platform` or `gqc.service`
   imports the world, the simulation or the lab.
2. **The world does not read the platform's settings.** `world.py` never reads `platform.yml` or `designs.yml`.
3. **Same luck for every design.** All randomness is keyed (`gqc.rng.keyed`) by seed and by what it is about, so
   every design sees the same customers, the same bursts, the same reviewer mistakes. The crash lab draws the same
   interleavings for every saga variant.
4. **The model reads and code decides.** The lending forecast and the quota risk score only produce numbers; the
   ledger, the thresholds in `platform.yml` and the state machine in `gqc.domain` decide.
5. **A reservation is held once and released once.** Every step of the saga is one local transaction with a
   version check; messages leave through the outbox written in the same transaction and are applied once through
   the inbox; a request carries an Idempotency-Key. `check_invariants` must return nothing after every lab scenario.
6. **Settings in config.** Thresholds, buffers, grace periods, weights and gates live in `config/*.yml`, not in code.
7. **Generated reports.** `REPORT.md`, the README results block and `web/public/data/report.json` are written by
   `python -m gqc.cli report`. CI regenerates them and fails on a diff. Never edit them by hand.

## The held-out rule

`python -m gqc.cli heldout` runs the held-out sites (burstier customers, more abuse) and the held-out lab
scenarios **once**. It writes `reports/heldout.lock` first, with the config hash; a second run exits with code 3.
CI checks that the lock was committed exactly once. Gates are set on the development sites and are not loosened
after the held-out run. New held-out seeds need a new name and an ADR.
