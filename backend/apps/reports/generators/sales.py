"""Sales & distribution registers, read from the raw Transaction fact table."""
from decimal import Decimal

from django.db.models import Sum

from apps.kpi_engine.models import Transaction
from apps.reports.generators._util import node_label_map
from apps.reports.registry import BaseReportGenerator, register
from apps.reports.renderers.base import Column, ReportResult

_Z = Decimal('0.00')


def _apply_filters(qs, params):
    if df := params.get('date_from'):
        qs = qs.filter(transaction_date__gte=df)
    if dt := params.get('date_to'):
        qs = qs.filter(transaction_date__lte=dt)
    if ch := params.get('channel'):
        qs = qs.filter(channel_code=ch)
    return qs


def _sales_register(level, title, params, scope):
    qs = Transaction.objects.filter(transaction_level=level, transaction_type=Transaction.SALE)
    qs = scope.filter_attributed_node(_apply_filters(qs, params))
    agg = (
        qs.values('attributed_node_id', 'sku_code')
        .annotate(qty=Sum('quantity'), gross=Sum('gross_amount'),
                  disc=Sum('discount_amount'), net=Sum('net_amount'))
        .order_by('attributed_node_id', 'sku_code')
    )
    agg = list(agg)
    labels = node_label_map(r['attributed_node_id'] for r in agg)

    rows, t_qty, t_gross, t_disc, t_net = [], _Z, _Z, _Z, _Z
    for r in agg:
        rows.append({
            'entity': labels.get(r['attributed_node_id'], f'#{r["attributed_node_id"]}'),
            'sku': r['sku_code'] or '—',
            'qty': r['qty'] or _Z,
            'gross': r['gross'] or _Z,
            'discount': r['disc'] or _Z,
            'net': r['net'] or _Z,
        })
        t_qty += r['qty'] or _Z
        t_gross += r['gross'] or _Z
        t_disc += r['disc'] or _Z
        t_net += r['net'] or _Z

    return ReportResult(
        title=title,
        columns=[
            Column('entity', 'Distributor / Outlet', width=26),
            Column('sku', 'SKU', width=16),
            Column('qty', 'Qty', 'decimal'),
            Column('gross', 'GSV', 'decimal'),
            Column('discount', 'Scheme Disc.', 'decimal'),
            Column('net', 'NSV', 'decimal'),
        ],
        rows=rows,
        summary={'qty': t_qty, 'gross': t_gross, 'discount': t_disc, 'net': t_net},
        meta={'filters': {k: v for k, v in params.items() if v}},
    )


@register('primary_sales_register')
class PrimarySalesGenerator(BaseReportGenerator):
    def run(self, params, scope, user):
        return _sales_register(Transaction.PRIMARY, 'Primary Sales Register', params, scope)


@register('secondary_sales_register')
class SecondarySalesGenerator(BaseReportGenerator):
    def run(self, params, scope, user):
        return _sales_register(Transaction.SECONDARY, 'Secondary Sales Register', params, scope)


@register('channel_mix')
class ChannelMixGenerator(BaseReportGenerator):
    """Net sales split by channel with % share — GT vs MT vs Ecom vs Rural."""

    def run(self, params, scope, user):
        qs = Transaction.objects.filter(transaction_type=Transaction.SALE)
        qs = scope.filter_attributed_node(_apply_filters(qs, params))
        agg = list(
            qs.values('channel_code').annotate(net=Sum('net_amount')).order_by('-net')
        )
        total = sum((r['net'] or _Z for r in agg), _Z)
        rows = [{
            'channel': r['channel_code'] or '(unset)',
            'net': r['net'] or _Z,
            'share': (round((r['net'] or _Z) / total * 100, 2) if total else _Z),
        } for r in agg]
        return ReportResult(
            title='Channel Mix',
            columns=[
                Column('channel', 'Channel', width=18),
                Column('net', 'Net Sales', 'decimal'),
                Column('share', 'Share %', 'percent'),
            ],
            rows=rows,
            summary={'net': total, 'share': Decimal('100.00') if total else _Z},
            meta={'filters': {k: v for k, v in params.items() if v}},
        )
