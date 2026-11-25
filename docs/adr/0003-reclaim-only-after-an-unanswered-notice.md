# 0003: Reclaim an unused reservation only after an unanswered notice

**Status:** accepted

**Context.** Some reservations are never started; some start days late. Releasing on a timer alone hands a late
customer's capacity to someone else.

**Decision.** After 36 hours from the start with zero use, send a notice. A "keep it" answer keeps the reservation
for good; no answer within 24 hours releases the rest of it. Billing starts at the first use (an assumption of this
simulation).

**Consequences.** The lab counts customers who came back to a released reservation; it is a gate (at most one per
site).
