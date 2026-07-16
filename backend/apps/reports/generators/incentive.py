"""Payout & exception registers (confidential — money)."""
from decimal import Decimal

from apps.incentives.models import Payout, PayoutException, PayoutRun
from apps.reports.registry import BaseReportGenerator, register
from apps.reports.renderers.base import Column, ReportResult

_Z = Decimal('0.00')


@register('payout_register')
class PayoutRegisterGenerator(BaseReportGenerator):
    """Node payout register: VP → gross → cap → net, with gatekeeper status.
    Confidential; computation_refs link each row to its ComputationLog."""

    def run(self, params, scope, user):
        qs = (
            Payout.objects.select_related('entity', 'entity__entity_type', 'scheme', 'run')
            .exclude(run__status__in=[PayoutRun.SUPERSEDED, PayoutRun.FAILED])
            .order_by('entity__path')
        )
        if period := params.get('period'):
            qs = qs.filter(target_period_id=period)
        if scheme := params.get('scheme'):
            qs = qs.filter(scheme_id=scheme)
        qs = scope.filter_entities(qs, 'entity__path')

        rows, total, refs = [], _Z, []
        for p in qs:
            rows.append({
                'entity': f'{p.entity.name} ({p.entity.code})',
                'scheme': p.scheme.name,
                'vp': p.eligible_vp,
                'gross': p.gross_payout,
                'capped': 'Yes' if p.capped else 'No',
                'gatekeeper': p.gatekeeper_status,
                'total': p.total_payout,
                'status': p.run.status,
            })
            total += p.total_payout
            if p.computation_id:
                refs.append(p.computation_id)

        return ReportResult(
            title='Payout Register',
            columns=[
                Column('entity', 'Node', width=26),
                Column('scheme', 'Scheme', width=22),
                Column('vp', 'Eligible VP', 'decimal'),
                Column('gross', 'Gross Payout', 'decimal'),
                Column('capped', 'Capped', width=8),
                Column('gatekeeper', 'Gatekeeper', width=14),
                Column('total', 'Net Payout', 'decimal'),
                Column('status', 'Run Status', width=14),
            ],
            rows=rows,
            summary={'total': total},
            confidential=True,
            meta={'filters': {k: v for k, v in params.items() if v},
                  'computation_refs': refs},
        )


@register('exception_register')
class ExceptionRegisterGenerator(BaseReportGenerator):
    """Payout exceptions with the per-category treatment applied."""

    def run(self, params, scope, user):
        qs = (
            PayoutException.objects.select_related('entity', 'entity__entity_type')
            .order_by('-created_at')
        )
        if period := params.get('period'):
            qs = qs.filter(target_period_id=period)
        if status := params.get('status'):
            qs = qs.filter(status=status)
        qs = scope.filter_entities(qs, 'entity__path')

        rows = [{
            'entity': f'{e.entity.name} ({e.entity.code})',
            'category': e.category or '—',
            'sales_action': e.sales_kpi_action,
            'gatekeeper_action': e.gatekeeper_action,
            'status': e.status,
            'reason': (e.reason or '')[:80],
        } for e in qs]

        return ReportResult(
            title='Exception Register',
            columns=[
                Column('entity', 'Node', width=24),
                Column('category', 'Category', width=18),
                Column('sales_action', 'Sales KPI', width=16),
                Column('gatekeeper_action', 'Gatekeeper', width=16),
                Column('status', 'Status', width=12),
                Column('reason', 'Reason', width=40),
            ],
            rows=rows,
            meta={'filters': {k: v for k, v in params.items() if v}},
        )
