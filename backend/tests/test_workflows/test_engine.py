"""Pure engine — no DB. Exact boolean / datetime assertions."""
from datetime import datetime, timedelta

from apps.workflows.engine import evaluate_condition, sla_due_at, step_satisfied


class TestEvaluateCondition:
    def test_no_condition_runs(self):
        assert evaluate_condition({}, None) is True

    def test_gt_decimal_strings(self):
        cond = {'field': 'impact_amount', 'op': 'gt', 'value': '50000'}
        assert evaluate_condition({'impact_amount': '60000'}, cond) is True
        assert evaluate_condition({'impact_amount': '40000'}, cond) is False
        assert evaluate_condition({'impact_amount': '50000'}, cond) is False

    def test_gte_lte(self):
        assert evaluate_condition({'x': '50'}, {'field': 'x', 'op': 'gte', 'value': '50'}) is True
        assert evaluate_condition({'x': '50'}, {'field': 'x', 'op': 'lte', 'value': '50'}) is True

    def test_missing_or_nonnumeric_operand_is_false(self):
        cond = {'field': 'impact_amount', 'op': 'gt', 'value': '50000'}
        assert evaluate_condition({'impact_amount': None}, cond) is False
        assert evaluate_condition({}, cond) is False

    def test_eq_ne_in(self):
        assert evaluate_condition({'c': 'leave'}, {'field': 'c', 'op': 'eq', 'value': 'leave'}) is True
        assert evaluate_condition({'c': 'leave'}, {'field': 'c', 'op': 'ne', 'value': 'transfer'}) is True
        assert evaluate_condition(
            {'c': 'leave'}, {'field': 'c', 'op': 'in', 'value': ['leave', 'transfer']},
        ) is True


class TestStepSatisfied:
    def test_single_first_approval_carries(self):
        assert step_satisfied('single', 1, 0, 3) == 'approved'
        assert step_satisfied('single', 0, 0, 1) == 'pending'

    def test_any_first_approval_carries(self):
        assert step_satisfied('any', 1, 0, 4) == 'approved'

    def test_all_requires_every_assignee(self):
        assert step_satisfied('all', 2, 0, 3) == 'pending'
        assert step_satisfied('all', 3, 0, 3) == 'approved'

    def test_rejection_is_decisive(self):
        assert step_satisfied('all', 2, 1, 3) == 'rejected'
        assert step_satisfied('single', 0, 1, 1) == 'rejected'


def test_sla_due_at():
    now = datetime(2026, 6, 1, 10, 0, 0)
    assert sla_due_at(now, 48) == now + timedelta(hours=48)
    assert sla_due_at(now, None) is None
    assert sla_due_at(now, 0) is None
