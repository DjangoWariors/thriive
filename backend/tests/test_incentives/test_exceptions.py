"""ExceptionService — duplicate-live guard, maker-checker, precedence, VariablePay rules."""
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.incentives.models import PayoutException
from apps.incentives.services import ExceptionService, VariablePayService

from .conftest import mk_exception, mk_scheme

D = Decimal


def _user(email):
    from apps.accounts.models import User
    return User.objects.create_user(email=email, password='pass')


@pytest.mark.django_db
class TestExceptionLifecycle:
    def test_create_pending(self, tree, period):
        u = _user('maker@x.com')
        exc = ExceptionService.create({
            'entity': tree['ase1'], 'target_period': period,
            'category': 'medical_leave', 'sales_kpi_action': 'default_1x',
            'execution_kpi_action': 'actual_performance',
            'gatekeeper_action': 'no_exemption', 'reason': '15 days medical leave',
        }, actor=u)
        assert exc.status == PayoutException.PENDING
        assert exc.requested_by == u

    def test_duplicate_live_rejected(self, tree, period):
        mk_exception(tree['ase1'], period, status=PayoutException.PENDING)
        with pytest.raises(BusinessError, match='already exists'):
            ExceptionService.create({
                'entity': tree['ase1'], 'target_period': period,
                'sales_kpi_action': 'zero', 'execution_kpi_action': 'zero',
                'gatekeeper_action': 'no_exemption', 'reason': 'dup',
            })

    def test_rejected_exception_allows_new_one(self, tree, period):
        mk_exception(tree['ase1'], period, status=PayoutException.REJECTED)
        exc = ExceptionService.create({
            'entity': tree['ase1'], 'target_period': period,
            'sales_kpi_action': 'zero', 'execution_kpi_action': 'zero',
            'gatekeeper_action': 'no_exemption', 'reason': 'retry',
        })
        assert exc.status == PayoutException.PENDING

    def test_maker_checker_on_approve(self, tree, period):
        maker = _user('m@x.com')
        exc = mk_exception(tree['ase1'], period, status=PayoutException.PENDING,
                           requested_by=maker)
        with pytest.raises(BusinessError, match='maker-checker'):
            ExceptionService.approve(exc, maker)
        checker = _user('c@x.com')
        exc = ExceptionService.approve(exc, checker)
        assert exc.status == PayoutException.APPROVED
        assert exc.approved_by == checker

    def test_only_pending_can_be_approved(self, tree, period):
        exc = mk_exception(tree['ase1'], period)  # already approved
        with pytest.raises(BusinessError, match='pending'):
            ExceptionService.approve(exc, _user('c2@x.com'))

    def test_reject_with_reason(self, tree, period):
        exc = mk_exception(tree['ase1'], period, status=PayoutException.PENDING)
        exc = ExceptionService.reject(exc, _user('c3@x.com'), 'not justified')
        assert exc.status == PayoutException.REJECTED
        assert exc.rejection_reason == 'not justified'

    def test_entity_type_must_match_scheme(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        with pytest.raises(BusinessError, match='target entity type'):
            ExceptionService.create({
                'entity': tree['asm'],  # ASM, scheme targets ASE
                'target_period': period, 'scheme': scheme,
                'sales_kpi_action': 'zero', 'execution_kpi_action': 'zero',
                'gatekeeper_action': 'no_exemption', 'reason': 'x',
            })

    def test_scheme_specific_overrides_scheme_null(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        general = mk_exception(tree['ase1'], period, sales='default_1x')
        specific = mk_exception(tree['ase1'], period, scheme=scheme, sales='zero')
        resolved = ExceptionService.approved_for(period, scheme)
        assert resolved[tree['ase1'].pk] == specific
        # An entity with only the general row resolves to it
        general2 = mk_exception(tree['ase2'], period, sales='default_1x')
        resolved = ExceptionService.approved_for(period, scheme)
        assert resolved[tree['ase2'].pk] == general2
        assert general.pk != specific.pk


@pytest.mark.django_db
class TestExceptionUpdate:
    def test_update_pending_validates_clash(self, tree, period):
        mk_exception(tree['ase2'], period, status=PayoutException.PENDING)
        exc = mk_exception(tree['ase1'], period, status=PayoutException.PENDING)
        with pytest.raises(BusinessError, match='already exists'):
            ExceptionService.update_pending(exc, {'entity': tree['ase2']})

    def test_update_pending_validates_scheme_entity_type(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        exc = mk_exception(tree['asm'], period, status=PayoutException.PENDING)
        with pytest.raises(BusinessError, match='target entity type'):
            ExceptionService.update_pending(exc, {'scheme': scheme})

    def test_update_pending_saves_and_audits(self, tree, period):
        from apps.audit.models import AuditLog
        exc = mk_exception(tree['ase1'], period, status=PayoutException.PENDING)
        u = _user('editor@x.com')
        exc = ExceptionService.update_pending(
            exc, {'sales_kpi_action': 'default_1x', 'reason': 'revised'}, actor=u,
        )
        exc.refresh_from_db()
        assert exc.sales_kpi_action == 'default_1x'
        assert exc.reason == 'revised'
        assert AuditLog.objects.filter(
            entity_type='incentives.PayoutException', entity_id=exc.pk, action='update',
        ).exists()

    def test_update_pending_resyncs_category_ref(self, tree, period):
        from datetime import date
        from apps.incentives.models import ExceptionCategory
        cat = ExceptionCategory.objects.create(
            code='medical_leave', name='Medical leave', effective_from=date.today(),
        )
        exc = mk_exception(tree['ase1'], period, status=PayoutException.PENDING)
        assert exc.category_ref is None
        exc = ExceptionService.update_pending(exc, {'category': 'medical_leave'})
        assert exc.category_ref == cat
        exc = ExceptionService.update_pending(exc, {'category': ''})
        assert exc.category_ref is None

    def test_update_non_pending_rejected(self, tree, period):
        exc = mk_exception(tree['ase1'], period)  # approved
        with pytest.raises(BusinessError, match='Only pending'):
            ExceptionService.update_pending(exc, {'reason': 'too late'})


@pytest.mark.django_db
class TestVariablePay:
    def test_negative_amount_rejected(self, tree, period):
        with pytest.raises(BusinessError, match='negative'):
            VariablePayService.upsert(tree['ase1'], period, D('-1'))

    def test_eligible_days_capped_at_period(self, tree, period):
        with pytest.raises(BusinessError, match='exceeds'):
            VariablePayService.upsert(tree['ase1'], period, D('50000'),
                                      eligible_working_days=25)

    def test_upsert_updates_in_place(self, tree, period):
        VariablePayService.upsert(tree['ase1'], period, D('50000.00'))
        vp = VariablePayService.upsert(tree['ase1'], period, D('60000.00'),
                                       eligible_working_days=10)
        assert vp.amount == D('60000.00')
        assert vp.eligible_working_days == 10
        from apps.incentives.models import VariablePay
        assert VariablePay.objects.filter(entity=tree['ase1'], target_period=period).count() == 1

    def test_bulk_import_all_or_nothing(self, tree, period):
        result = VariablePayService.bulk_import([
            {'entity_code': 'ASE1', 'amount': '50000'},
            {'entity_code': 'NOPE', 'amount': '50000'},
        ], period)
        assert result['errors']
        from apps.incentives.models import VariablePay
        assert VariablePay.objects.count() == 0  # nothing created

    def test_bulk_import_success(self, tree, period):
        result = VariablePayService.bulk_import([
            {'entity_code': 'ASE1', 'amount': '50000', 'eligible_working_days': 10},
            {'entity_code': 'ASE2', 'amount': '60000'},
        ], period)
        assert result == {'created': 2, 'updated': 0, 'errors': []}

    def test_bulk_import_bad_working_days_is_row_error(self, tree, period):
        result = VariablePayService.bulk_import([
            {'entity_code': 'ASE1', 'amount': '50000', 'eligible_working_days': 'abc'},
            {'entity_code': 'ASE2', 'amount': '60000', 'eligible_working_days': -3},
        ], period)
        assert [e['row'] for e in result['errors']] == [1, 2]
        assert 'Invalid eligible_working_days.' in result['errors'][0]['errors']
        assert 'eligible_working_days cannot be negative.' in result['errors'][1]['errors']
        from apps.incentives.models import VariablePay
        assert VariablePay.objects.count() == 0
