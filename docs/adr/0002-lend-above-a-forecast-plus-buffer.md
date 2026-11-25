# 0002: Lend idle reserved nodes above a forecast plus a learned buffer

**Status:** accepted

**Context.** Reserved nodes sit idle at night, between bursts and before a ramp. Lending them to preemptible jobs
raises utilisation, but taking them back takes a step (15 minutes here): if the customer's use jumps in that step,
they are short of nodes they paid to have.

**Decision.** For each reservation, after a day of watching it, forecast the next step as the largest of the last
step, the same time yesterday and the same time a week ago, add a buffer equal to the 99.9th percentile of past
under-forecasts (at least one node), and lend only what is above that. `naive` (lend everything idle) and `off`
are kept as ablations.

**Consequences.** On the development sites the plane lends about half of what naive lending does and keeps reserved
use met at 99.97% against 97.8%. Some reservations are still short once or twice (a first burst before any history);
the README reports that count instead of hiding it.
