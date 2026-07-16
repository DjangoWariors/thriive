"""Target vs achievement, read from computed Achievement rows."""
from decimal import Decimal

from apps.achievements.models import Achievement
from apps.reports.registry import BaseReportGenerator, register
from apps.reports.renderers.base import Column, ReportResult

_Z = Decimal('0.00')


@register('target_vs_achievement')
class TargetVsAchievementGenerator(BaseReportGenerator):
    """Per entity × KPI, target vs achieved with % and gap. Scoped to subtree."""

    def run(self, params, scope, user):
        qs = (
            Achievement.objects.filter(is_active=True)
            .select_related('entity', 'entity__entity_type', 'kpi', 'channel')
            .order_by('entity__path', 'kpi__code')
        )
        if period := params.get('period'):
            qs = qs.filter(target_period_id=period)
        if kpi := params.get('kpi'):
            qs = qs.filter(kpi__code=kpi)
        qs = scope.filter_entities(qs, 'entity__path')

        rows, t_target, t_ach = [], _Z, _Z
        for a in qs:
            rows.append({
                'entity': f'{a.entity.name} ({a.entity.code})',
                'type': a.entity.entity_type.name,
                'kpi': a.kpi.name,
                'channel': a.channel.name if a.channel else '—',
                'target': a.target_value,
                'achieved': a.achieved_value,
                'pct': a.achievement_pct,
                'gap': a.gap_to_target,
            })
            t_target += a.target_value
            t_ach += a.achieved_value

        return ReportResult(
            title='Target vs Achievement',
            columns=[
                Column('entity', 'Node', width=26),
                Column('type', 'Level', width=16),
                Column('kpi', 'KPI', width=20),
                Column('channel', 'Channel', width=12),
                Column('target', 'Target', 'decimal'),
                Column('achieved', 'Achieved', 'decimal'),
                Column('pct', 'Ach %', 'percent'),
                Column('gap', 'Gap', 'decimal'),
            ],
            rows=rows,
            summary={'target': t_target, 'achieved': t_ach},
            meta={'filters': {k: v for k, v in params.items() if v}},
        )
