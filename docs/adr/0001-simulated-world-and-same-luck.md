# 0001: A simulated cloud with hidden truth, and the same luck for every design

**Status:** accepted

**Context.** Capacity decisions (lend this idle node, release that reservation, approve this quota) can only be
judged against what really happened next: did the customer need the node, did they come back, was the organisation
abusive. A real fleet does not tell you what would have happened under the other policy.

**Decision.** `gqc.world` generates clusters, reservations with a per-step usage profile (steady, diurnal, bursty,
ramp, late start, never used), self-serve organisations with demand and an abuse flag, and quota requests. The
control plane sees usage one step at a time. Every random draw is keyed by seed and subject, so every design runs on
identical customers and identical reviewer mistakes.

**Consequences.** Differences between designs are caused by the designs. The numbers are only as good as the
generator: see the README's limits.
