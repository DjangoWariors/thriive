"""Master & roster reports."""
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Node
from apps.reports.registry import BaseReportGenerator, register
from apps.reports.renderers.base import Column, ReportResult


@register('entity_roster')
class NodeRosterGenerator(BaseReportGenerator):
    """Org directory / field-force roster, scoped to the requester's subtree."""

    def run(self, params, scope, user) -> ReportResult:
        qs = (
            Node.objects.filter(is_current=True)
            .select_related('entity_type', 'parent', 'channel')
            .order_by('path')
        )
        qs = scope.filter_entities(qs, 'path')
        if etype := params.get('entity_type'):
            qs = qs.filter(entity_type__code=etype)
        if status := params.get('status'):
            qs = qs.filter(status=status)

        entities = list(qs)
        # Geography = territories currently owned via the Assignment bridge.
        owner_map = AssignmentService.open_owner_scopes_map([e.pk for e in entities])

        rows = [{
            'code': e.code,
            'name': e.name,
            'type': e.entity_type.name,
            'parent': e.parent.name if e.parent else '',
            'channel': e.channel.name if e.channel else '',
            'geography': ', '.join(a.scope.name for a in owner_map.get(e.pk, [])),
            'loginable': 'Yes' if e.entity_type.is_loginable else 'No',
            'status': e.status,
        } for e in entities]

        return ReportResult(
            title='Node Roster',
            columns=[
                Column('code', 'Code', width=14),
                Column('name', 'Name', width=24),
                Column('type', 'Type', width=18),
                Column('parent', 'Reports To', width=22),
                Column('channel', 'Channel', width=14),
                Column('geography', 'Geography', width=18),
                Column('loginable', 'Login', width=8),
                Column('status', 'Status', width=12),
            ],
            rows=rows,
            meta={'filters': {k: v for k, v in params.items() if v}},
        )
