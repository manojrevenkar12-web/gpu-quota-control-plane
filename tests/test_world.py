import numpy as np

from gqc.world.world import build_site, keeps_after_notice


def test_same_luck_for_every_build() -> None:
    a, b = build_site(11), build_site(11)
    assert [r.nodes for r in a.reservations] == [r.nodes for r in b.reservations]
    assert all(np.array_equal(x.usage, y.usage) for x, y in zip(a.reservations, b.reservations, strict=True))
    assert [q.nodes for q in a.requests] == [q.nodes for q in b.requests]


def test_usage_never_exceeds_the_reservation() -> None:
    s = build_site(12)
    for r in s.reservations:
        assert r.usage.min() >= 0 and r.usage.max() <= r.nodes
        assert len(r.usage) == r.end - r.start


def test_requests_are_in_time_order_with_matching_ids() -> None:
    s = build_site(13)
    assert [q.id for q in s.requests] == list(range(len(s.requests)))
    assert [q.step for q in s.requests] == sorted(q.step for q in s.requests)


def test_notice_answers_depend_on_intent() -> None:
    s = build_site(11, "heldout")
    never = [keeps_after_notice(s, r) for r in s.reservations if r.profile == "never"]
    others = [keeps_after_notice(s, r) for r in s.reservations if r.profile != "never"]
    assert np.mean(others) > np.mean(never) if never else True
