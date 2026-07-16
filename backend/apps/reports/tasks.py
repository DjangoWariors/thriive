from celery import shared_task

from apps.reports.models import ReportExecution, ReportSchedule
from apps.reports.services import ReportService


@shared_task(bind=True, max_retries=2)
def generate_report_task(self, execution_id: int) -> dict:
    execution = ReportExecution.objects.select_related('definition', 'requested_by').get(
        pk=execution_id)
    ReportService.run_execution(execution)
    return {'execution_id': execution_id, 'status': execution.status,
            'rows': execution.row_count}


@shared_task
def run_scheduled_report(schedule_id: int) -> dict:
    from apps.reports.schedule_service import ReportScheduleService
    schedule = ReportSchedule.objects.select_related('definition').filter(
        pk=schedule_id, is_enabled=True, is_active=True).first()
    if schedule is None:
        return {'skipped': True, 'schedule_id': schedule_id}
    return ReportScheduleService.run(schedule)
