# SKILLS.md

Repeatable tasks, each with the commands and the check that tells you it worked.

## Change a control-plane setting
1. Edit `config/platform.yml` (never the world).
2. `python -m gqc.cli dev && python -m gqc.cli gate dev`.
3. Commit the setting with the regenerated `reports/dev.json`, `REPORT.md`, `README.md` and `web/public/data/report.json`.

## Add a design or an ablation
1. Add it under `designs:` in `config/designs.yml` with the switches it changes; list it in `ablations`.
2. If it needs a new switch, read it in `gqc/sim/evaluate.py` and implement the behaviour in `gqc/platform/`.
3. Add its short name to `SHORT` in `gqc/lab/report.py`; run `python -m gqc.cli dev`.

## Add a safeguard variant to the crash lab
1. Add a field to `Safeguards` in `gqc/platform/saga.py` and honour it in the steps.
2. Add the variant to `VARIANTS` and a label to `FAULT_LABEL`.
3. `pytest tests/test_saga.py`: the full saga must still break nothing, the new variant must break something.

## Add an invariant
1. Add the check to `check_invariants` with a short kind name, and a label to `KIND` in `report.py`.
2. Add a unit test that builds the broken state by hand and sees the check fire.

## Run the held-out sites (once)
1. Make sure the gates in `config/gates.yml` are final and committed.
2. `python -m gqc.cli heldout`, then commit `reports/heldout.lock` and `reports/heldout.json` together with the regenerated reports in one commit.

## Refresh the console screenshots
`cd web && npm run build`, serve `web/dist`, and capture `docs/screenshots/console.png` (light, full page) and `console-dark.png`.

## Run the API
`python -m gqc.cli serve` or `docker build -t gqc . && docker run -p 8080:8080 gqc`; then `PUT /v1/capacity/{cluster}`,
`PUT /v1/quotas/{org}/{service}`, and `POST /v1/reservations` with an `Idempotency-Key` header.
