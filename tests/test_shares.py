import pytest

from app.shares import split_evenly, validate_shares


@pytest.mark.parametrize("n", range(1, 15))
def test_split_sums_to_100(n):
    shares = split_evenly(list(range(n)))
    assert sum(shares.values()) == 100
    assert max(shares.values()) - min(shares.values()) <= 1


def test_split_examples():
    assert split_evenly([1]) == {1: 100}
    assert split_evenly([1, 2]) == {1: 50, 2: 50}
    assert split_evenly([1, 2, 3]) == {1: 34, 2: 33, 3: 33}
    assert split_evenly([]) == {}


def test_validate():
    validate_shares({1: 70, 2: 30})
    with pytest.raises(ValueError):
        validate_shares({1: 70, 2: 20})
    with pytest.raises(ValueError):
        validate_shares({})
    with pytest.raises(ValueError):
        validate_shares({1: 120, 2: -20})
