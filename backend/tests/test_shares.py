import itertools

import pytest

from app.shares import allocate, shares_after_add, shares_after_remove, shares_equal


@pytest.mark.parametrize("n", range(1, 13))
def test_equal_always_sums_to_100(n):
    shares = shares_equal(n)
    assert len(shares) == n
    assert sum(shares) == 100
    assert max(shares) - min(shares) <= 1


def test_equal_three_gives_34_33_33():
    assert shares_equal(3) == [34, 33, 33]


def test_add_to_single_offer_splits_evenly():
    assert shares_after_add([100]) == [50, 50]


def test_add_keeps_ratio_of_existing_offers():
    after = shares_after_add([80, 20])
    assert sum(after) == 100
    assert after[0] > after[2] > after[1]  # 80 остаётся самым большим, 20 самым маленьким


def test_add_to_empty_gives_100():
    assert shares_after_add([]) == [100]


def test_add_to_even_split_stays_even():
    assert shares_after_add([50, 50]) == [34, 33, 33]
    assert shares_after_add([34, 33, 33]) == [25, 25, 25, 25]


def test_remove_from_even_split_stays_even():
    assert shares_after_remove([34, 33, 33], 1) == [50, 50]
    assert shares_after_remove([50, 50], 0) == [100]
    assert shares_after_remove([25, 25, 25, 25], 3) == [34, 33, 33]


def test_remove_redistributes_proportionally_for_custom_split():
    assert shares_after_remove([50, 30, 20], 0) == [60, 40]
    assert shares_after_remove([70, 20, 10], 2) == [78, 22]


def test_remove_when_remaining_have_zero_shares_splits_evenly():
    assert shares_after_remove([100, 0, 0], 0) == [50, 50]


def test_allocate_handles_empty_and_zero_weights():
    assert allocate([]) == []
    assert allocate([0, 0, 0]) == [34, 33, 33]


def test_sum_is_100_for_many_combinations():
    for existing in itertools.chain(
        ([x] for x in (1, 50, 100)),
        itertools.product((0, 1, 33, 34, 50, 99), repeat=2),
        itertools.product((1, 7, 20, 40), repeat=3),
    ):
        existing = list(existing)
        assert sum(shares_after_add(existing)) == 100
        if len(existing) > 1:
            for i in range(len(existing)):
                assert sum(shares_after_remove(existing, i)) == 100
