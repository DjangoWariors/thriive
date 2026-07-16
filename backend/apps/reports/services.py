"""Report engine — the only layer that writes ReportExecution. Called by views
and the schedule runner; renders via the registry + renderers; dispatches heavy
work through the shared jobs dispatcher."""
from datetime import timedelta

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.audit.services import AccessService
from apps.core.exceptions import BusinessError
from apps.core.permissions import _rank, highest_level
from apps.jobs.dispatch import run_or_dispatch
from apps.reports.models import ReportDefinition, ReportExecution
from apps.reports.registry import get_generator
from apps.reports.renderers import csv_stream, pdf, xlsx
from apps.reports.scope import ReportScope, build_scope

_RENDERERS = {
    ReportExecution.Format.XLSX: (xlsx.render, 'xlsx'),
    ReportExecution.Format.PDF: (pdf.render, 'pdf'),
    ReportExecution.Format.CSV: (csv_stream.render, 'csv'),
}
_ARTIFACT_TTL_DAYS = 7


def validate_params(schema: list, params: dict) -> None:
    """Lightweight param validation against the definition's param_schema
    (same shape as NodeType.attribute_schema)."""
    errors = []
    for field in schema or []:
        key, required = field.get('key'), field.get('required', False)
        value = params.get(key)
        if required and (value is None or value == ''):
            errors.append(f'{field.get("label", key)} is required.')
        if value and field.get('type') == 'choice' and field.get('options'):
            if value not in field['options']:
                errors.append(f'{field.get("label", key)}: "{value}" is not a valid choice.')
    if errors:
        raise BusinessError('; '.join(errors), code='invalid_report_params')


class ReportService:

    @staticmethod
    def list_runnable(user) -> list[ReportDefinition]:
        defs = ReportDefinition.objects.filter(is_active=True)
        if getattr(user, 'is_superuser', False):
            return list(defs)
        return [d for d in defs if _rank(highest_level(user, d.required_permission)) > 0]

    @staticmethod
    def can_run(user, definition: ReportDefinition) -> bool:
        if getattr(user, 'is_superuser', False):
            return True
        return _rank(highest_level(user, definition.required_permission)) > 0

    @staticmethod
    def build_execution(definition, params: dict, fmt: str, user) -> ReportExecution:
        """Validate + scope-freeze + create a queued ReportExecution. Shared by the
        API (which then dispatches) and the scheduler (which runs it inline)."""
        if not ReportService.can_run(user, definition):
            raise BusinessError('You do not have permission to run this report.',
                                code='report_forbidden')
        if fmt not in dict(ReportExecution.Format.choices):
            raise BusinessError(f'Unsupported format "{fmt}".', code='bad_format')

        validate_params(definition.param_schema, params)
        scope = build_scope(user, definition.required_permission)

        execution = ReportExecution.objects.create(
            definition=definition,
            requested_by=user if getattr(user, 'is_authenticated', False) else None,
            parameters=params,
            scope_snapshot=scope.to_snapshot(),
            status=ReportExecution.Status.QUEUED,
            format=fmt,
        )
        if definition.is_confidential:
            AccessService.record(user, definition.code, action='export', object_id=execution.pk)
        return execution

    @staticmethod
    def generate(definition_code: str, params: dict, fmt: str, user) -> ReportExecution:
        definition = ReportDefinition.objects.filter(code=definition_code, is_active=True).first()
        if definition is None:
            raise BusinessError(f'Unknown report "{definition_code}".', code='unknown_report')
        execution = ReportService.build_execution(definition, params, fmt, user)

        from apps.reports.tasks import generate_report_task
        return run_or_dispatch(generate_report_task, execution)

    # ── task-side (only the Celery task / runner calls these) ───────────────────

    @staticmethod
    def run_execution(execution: ReportExecution) -> ReportExecution:
        execution.status = ReportExecution.Status.RUNNING
        execution.started_at = timezone.now()
        execution.save(update_fields=['status', 'started_at', 'updated_at'])
        try:
            generator_cls = get_generator(execution.definition.code)
            if generator_cls is None:
                raise BusinessError(f'No generator registered for "{execution.definition.code}".')
            scope = ReportScope.from_snapshot(execution.scope_snapshot)
            result = generator_cls().run(execution.parameters, scope, execution.requested_by)

            render_fn, ext = _RENDERERS[execution.format]
            content = render_fn(result)
            filename = f'{execution.definition.code}-{execution.pk}.{ext}'

            execution.file.save(filename, ContentFile(content), save=False)
            execution.file_size = len(content)
            execution.row_count = result.row_count
            execution.computation_refs = (result.meta or {}).get('computation_refs', [])
            execution.expires_at = timezone.now() + timedelta(days=_ARTIFACT_TTL_DAYS)
            execution.status = ReportExecution.Status.COMPLETED
            execution.finished_at = timezone.now()
            execution.save()
        except Exception as exc:  # noqa: BLE001 — record any failure for the user to see
            execution.status = ReportExecution.Status.FAILED
            execution.error = str(exc)
            execution.finished_at = timezone.now()
            execution.save(update_fields=['status', 'error', 'finished_at', 'updated_at'])
        return execution

    @staticmethod
    def record_download(user, execution: ReportExecution) -> None:
        if execution.definition.is_confidential:
            AccessService.record(user, execution.definition.code,
                                 action='download', object_id=execution.pk)
