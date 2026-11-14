import itertools

import pytest

from app.shares import allocate, distribute, shares_equal


@pytest.mark.parametrize("n", range(1, 13))
def test_equal_always_sums_to_100(n):
    shares = shares_equal(n)
    assert len(shares) == n
    assert sum(shares) == 100
    assert max(shares) - min(shares) <= 1


def test_equal_three_gives_34_33_33():
    assert shares_equal(3) == [34, 33, 33]


def test_allocate_handles_empty_and_zero_weights():
    assert allocate([]) == []
    assert allocate([0, 0, 0]) == [34, 33, 33]


def test_allocate_keeps_proportions():
    assert allocate([50, 30, 20]) == [50, 30, 20]
    assert allocate([1, 1], total=75) == [38, 37]


# ------------------------------------------------------------------ pin
def test_distribute_without_pins_is_equal():
    assert distribute([None, None, None]) == [34, 33, 33]
    assert distribute([None]) == [100]
    assert distribute([]) == []


def test_distribute_pinned_share_stays_and_the_rest_is_split_evenly():
    assert distribute([25, None, None, None]) == [25, 25, 25, 25]
    assert distribute([25, None, None]) == [25, 38, 37]
    assert distribute([None, 60, None]) == [20, 60, 20]


def test_distribute_all_pinned_must_add_up_to_100():
    assert distribute([25, 25, 25, 25]) == [25, 25, 25, 25]
    with pytest.raises(ValueError, match="add up to 100"):
        distribute([50, 30])


def test_distribute_pins_must_leave_room_for_free_offers():
    with pytest.raises(ValueError, match="no room"):
        distribute([100, None])
    with pytest.raises(ValueError, match="no room"):
        distribute([99, None, None])
    assert distribute([98, None, None]) == [98, 1, 1]


def test_distribute_always_sums_to_100():
    for pins in itertools.product((None, 1, 10, 33, 50), repeat=4):
        try:
            result = distribute(list(pins))
        except ValueError:
            continue
        assert sum(result) == 100
        assert all(r == p for r, p in zip(result, pins) if p is not None)