"""Compliance & audit exports."""
from apps.audit.models import AuditLog
from apps.reports.generators._util import user_label_map
from apps.reports.registry import BaseReportGenerator, register
from apps.reports.renderers.base import Column, ReportResult


@register('audit_trail_export')
class AuditTrailExportGenerator(BaseReportGenerator):
    """Audit log export for auditors. Confidential. Not entity-scoped — only
    users with the audit_logs permission can run it (enforced by the service)."""

    def run(self, params, scope, user):
        qs = AuditLog.objects.all().order_by('-id')
        if df := params.get('date_from'):
            qs = qs.filter(timestamp__date__gte=df)
        if dt := params.get('date_to'):
            qs = qs.filter(timestamp__date__lte=dt)
        if action := params.get('action'):
            qs = qs.filter(action=action)
        qs = qs[:50000]  # bounded export

        rows = list(qs)
        labels = user_label_map(r.user_id for r in rows)
        out = [{
            'timestamp': r.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'user': labels.get(r.user_id, 'system'),
            'action': r.action,
            'record_type': r.entity_type,
            'record_id': r.entity_id,
            'row_hash': r.row_hash[:12],
        } for r in rows]

        return ReportResult(
            title='Audit Trail Export',
            columns=[
                Column('timestamp', 'Timestamp', width=20),
                Column('user', 'User', width=22),
                Column('action', 'Action', width=16),
                Column('record_type', 'Record Type', width=24),
                Column('record_id', 'Record ID', 'integer'),
                Column('row_hash', 'Integrity', width=14),
            ],
            rows=out,
            confidential=True,
            meta={'filters': {k: v for k, v in params.items() if v}},
        )
