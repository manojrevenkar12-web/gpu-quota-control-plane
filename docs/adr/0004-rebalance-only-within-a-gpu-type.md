# 0004: Rebalance only within a GPU type, only for flexible customers, and never half-way

**Status:** accepted

**Context.** A request can fail in one region while the same GPU type has room in another.

**Decision.** Customers who said they accept another region are placed where that GPU type has the most headroom.
If a request still does not fit, flexible reservations that have not started may be moved to make room; if the moves
do not free enough, every move is undone. Running reservations never move.

**Consequences.** Fewer requests are turned away; the moves are counted in the report.
