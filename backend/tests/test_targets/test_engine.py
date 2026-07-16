"""Pure disaggregation engine — exact Decimals + the Σ children == parent invariant."""
from decimal import Decimal

from apps.targets import disaggregator


def _sum(d):
    return sum(d.values(), Decimal('0'))


def test_equal_split_reconciles():
    out = disaggregator.split_spatial(10000, [(1, 1), (2, 1), (3, 1)], unit=1)
    assert out == {1: Decimal('3333'), 2: Decimal('3333'), 3: Decimal('3334')}
    assert _sum(out) == Decimal('10000')


def test_proportional_split():
    out = disaggregator.split_spatial(10000, [(1, 1000), (2, 3000)], unit=1)
    assert out == {1: Decimal('2500'), 2: Decimal('7500')}


def test_driver_weighted_split():
    out = disaggregator.split_spatial(10000, [(1, 2), (2, 8)], unit=1)
    assert out == {1: Decimal('2000'), 2: Decimal('8000')}


def test_rounding_to_unit_with_remainder_on_last():
    out = disaggregator.split_spatial(10000, [(1, 1), (2, 1), (3, 1)], unit=100)
    assert out == {1: Decimal('3300'), 2: Decimal('3300'), 3: Decimal('3400')}
    assert _sum(out) == Decimal('10000')


def test_zero_weights_fall_back_to_equal():
    out = disaggregator.split_spatial(900, [(1, 0), (2, 0), (3, 0)], unit=1)
    assert _sum(out) == Decimal('900')
    assert out[1] == out[2] == Decimal('300')


def test_reconciliation_invariant_across_weights():
    # Whatever the weights, the parts must sum back to the whole exactly.
    for weights in ([7, 3], [1, 1, 1, 1], [13, 0, 99, 4], [1, 2, 3, 4, 5]):
        parts = list(enumerate(weights, start=1))
        out = disaggregator.split_spatial(Decimal('123456.7890'), parts, unit=Decimal('0.01'))
        assert _sum(out) == Decimal('123456.7890')
