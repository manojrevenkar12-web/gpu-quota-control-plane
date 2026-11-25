# 0005: A saga with an outbox, an inbox, version checks and idempotency keys

**Status:** accepted

**Context.** A reservation touches three owners: the reservation record, the cluster's capacity and the
organisation's quota. A distributed transaction across them is not available; a crash between writes, a retried
request or a duplicated message must not oversell capacity, double-charge quota or leave a reservation stuck.

**Decision.** Each step is one local transaction on a versioned store (commit fails if anything read has changed).
The API writes the reservation, the idempotency key and the first message in one transaction (outbox). A relay sends
outbox messages at least once; consumers record each message id in an inbox in the same transaction as their effect.
Over quota, the quota step queues a compensation that returns the held capacity. On start-up the service relays
whatever is left.

**Consequences.** The crash lab interleaves steps at random, kills them mid-way, retries requests and delivers
messages twice: the full saga breaks no invariant in any scenario, and removing any one safeguard breaks some. The
same code runs in the API on SQLite, where a threaded test checks that concurrent writers never oversell.
