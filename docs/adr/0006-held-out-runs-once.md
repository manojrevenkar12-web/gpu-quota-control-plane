# 0006: The held-out sites run once, behind a lock

**Status:** accepted

**Context.** Tuning on the sites you report on overstates the result.

**Decision.** Gates and settings are fixed on three development sites. The held-out sites (burstier customers, more
never-used reservations, more abuse) and 600 held-out lab scenarios run once with `gqc heldout`, which writes
`reports/heldout.lock` (seeds and config hash) before running. A second run exits with code 3; CI checks the lock
was committed once.

**Consequences.** If the held-out run fails a gate, the failure stays in the report.
