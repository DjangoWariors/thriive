from decimal import Decimal

import pytest

from apps.kpi_engine.expressions import ExpressionError, extract_names, safe_eval


def test_basic_arithmetic():
    assert safe_eval('1 + 2 * 3', {}) == Decimal('7')


def test_variables_and_weights():
    result = safe_eval('0.7 * A + 0.3 * B', {'A': Decimal('100'), 'B': Decimal('50')})
    assert result == Decimal('85.0')


def test_parentheses_and_unary():
    assert safe_eval('-(A - B)', {'A': Decimal('3'), 'B': Decimal('10')}) == Decimal('7')


def test_division_by_zero_yields_zero():
    assert safe_eval('A / B', {'A': Decimal('10'), 'B': Decimal('0')}) == Decimal('0')


def test_unknown_reference_raises():
    with pytest.raises(ExpressionError):
        safe_eval('A + C', {'A': Decimal('1')})


def test_malformed_expression_raises():
    with pytest.raises(ExpressionError):
        safe_eval('A +', {'A': Decimal('1')})


def test_no_function_calls_allowed():
    with pytest.raises(ExpressionError):
        safe_eval('__import__("os")', {})


def test_extract_names():
    assert extract_names('0.6 * SECONDARY_NSV + 0.4 * ECO') == {'SECONDARY_NSV', 'ECO'}
