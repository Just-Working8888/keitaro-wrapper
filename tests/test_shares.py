import pytest

from app.shares import distribute_evenly, rebalance, validate_shares


@pytest.mark.parametrize("n,expected", [
    (1, [100]), (2, [50, 50]), (3, [34, 33, 33]), (6, [17, 17, 17, 17, 16, 16]), (7, [15, 15, 14, 14, 14, 14, 14]),
])
def test_distribute_evenly(n, expected):
    shares = distribute_evenly(list(range(1, n + 1)))
    assert list(shares.values()) == expected
    assert sum(shares.values()) == 100


def test_distribute_sums_to_100_for_many():
    for n in range(1, 101):
        assert sum(distribute_evenly(list(range(n))).values()) == 100


def test_validate_shares():
    validate_shares({1: 60, 2: 40})
    with pytest.raises(ValueError):
        validate_shares({1: 60, 2: 50})
    with pytest.raises(ValueError):
        validate_shares({})
    with pytest.raises(ValueError):
        validate_shares({1: 120, 2: -20})


@pytest.mark.parametrize("active,pinned,expected", [
    ([1, 2, 3, 4], {}, [25, 25, 25, 25]),
    ([1, 2, 3, 4], {1: 25}, [25, 25, 25, 25]),
    ([1, 2, 3], {1: 25}, [25, 38, 37]),
    ([1, 2, 3, 4], {2: 50}, [17, 50, 17, 16]),
    ([1, 2], {1: 30, 2: 30}, [30, 30]),  # all pinned: left as is
    ([1, 2], {3: 90}, [50, 50]),  # pins of inactive offers are ignored
])
def test_rebalance(active, pinned, expected):
    assert list(rebalance(active, pinned).values()) == expected


def test_rebalance_rejects_pins_over_100():
    with pytest.raises(ValueError):
        rebalance([1, 2, 3], {1: 60, 2: 50})
