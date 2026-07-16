"""FMCG generators: registration smoke-render for all, data + scoping for sales."""
from datetime import date
from decimal import Decimal

import pytest

from apps.kpi_engine.models import Transaction
from apps.reports.registry import get_generator
from apps.reports.renderers import csv_stream, xlsx
from apps.reports.scope import ReportScope

pytestmark = pytest.mark.django_db

GLOBAL = ReportScope(is_global=True, home_path=None, home_entity_id=None)

ALL_CODES = [
    'primary_sales_register', 'secondary_sales_register', 'channel_mix',
    'target_vs_achievement', 'payout_register', 'exception_register',
    'entity_roster', 'audit_trail_export',
]


class TestRegistrationAndRender:
    @pytest.mark.parametrize('code', ALL_CODES)
    def test_every_report_registers_and_renders_empty(self, code):
        gen_cls = get_generator(code)
        assert gen_cls is not None, f'{code} has no registered generator'
        result = gen_cls().run({}, GLOBAL, None)
        # Both renderers must succeed on an empty (but well-formed) result.
        assert csv_stream.render(result).startswith(
            ','.join(c.label for c in result.columns).encode()[:5])
        assert xlsx.render(result)[:2] == b'PK'

    def test_seed_matches_registry(self, reports_seeded):
        from apps.reports.models import ReportDefinition
        for d in ReportDefinition.objects.all():
            assert get_generator(d.code) is not None, f'{d.code} seeded without a generator'


def _txn(entity_id, level, channel, sku, net, qty=1):
    from apps.assignments.models import Assignment
    a = Assignment.objects.filter(assignee_id=entity_id, role_in_scope='owner', is_active=True).first()
    node_id = a.scope_id if a else entity_id
    return Transaction.objects.create(
        attributed_node_id=node_id, transaction_date=date(2026, 6, 10),
        transaction_type=Transaction.SALE, transaction_level=level,
        channel_code=channel, sku_code=sku,
        gross_amount=Decimal(net), discount_amount=Decimal('0'),
        net_amount=Decimal(net), quantity=Decimal(qty), source='dms_sync',
    )


class TestSecondarySales:
    def test_aggregates_and_totals(self, org):
        _txn(org['ase1'].pk, Transaction.SECONDARY, 'GT', 'SKU1', '1000')
        _txn(org['ase1'].pk, Transaction.SECONDARY, 'GT', 'SKU1', '500')   # same group → sums
        _txn(org['ase2'].pk, Transaction.SECONDARY, 'MT', 'SKU2', '2000')

        result = get_generator('secondary_sales_register')().run({}, GLOBAL, None)
        assert result.row_count == 2                      # two (entity, sku) groups
        assert result.summary['net'] == Decimal('3500')   # 1000 + 500 + 2000

    def test_subtree_scope_excludes_outside(self, org):
        _txn(org['ase1'].pk, Transaction.SECONDARY, 'GT', 'SKU1', '1000')  # under ASM
        _txn(org['nsm'].pk, Transaction.SECONDARY, 'GT', 'SKU9', '9999')   # at NSM (above ASM)

        scope = ReportScope(is_global=False, home_path=org['asm'].path,
                            home_entity_id=org['asm'].pk)
        result = get_generator('secondary_sales_register')().run({}, scope, None)
        assert result.summary['net'] == Decimal('1000')   # NSM row excluded

    def test_channel_mix_share(self, org):
        _txn(org['ase1'].pk, Transaction.SECONDARY, 'GT', 'SKU1', '750')
        _txn(org['ase2'].pk, Transaction.SECONDARY, 'MT', 'SKU2', '250')
        result = get_generator('channel_mix')().run({}, GLOBAL, None)
        shares = {r['channel']: r['share'] for r in result.rows}
        assert shares['GT'] == Decimal('75.00')
        assert shares['MT'] == Decimal('25.00')
