from django.db import models

from apps.core.models import BaseModel


def report_upload_path(instance, filename):
    from datetime import date
    d = date.today()
    return f'reports/{d:%Y/%m}/{filename}'


class ReportDefinition(BaseModel):
    """
    Catalog entry for one report. Seeded (not user-created in v1). ``param_schema``
    reuses the NodeType attribute-schema shape so the frontend renders the
    parameter form dynamically. ``required_permission`` gates who may run it;
    ``is_confidential`` makes every run/download write an AccessLog.
    """

    class Category(models.TextChoices):
        SALES = 'sales', 'Sales & Distribution'
        COVERAGE = 'coverage', 'Coverage & Productivity'
        TARGETS = 'targets', 'Targets & Achievement'
        INCENTIVE = 'incentive', 'Incentive & Payout'
        COMPLIANCE = 'compliance', 'Compliance'
        MASTER = 'master', 'Master & Audit'

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=60, unique=True)   # matches a registered generator
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    description = models.TextField(blank=True, default='')
    param_schema = models.JSONField(default=list)          # [{key,label,type,required,options,...}]
    default_formats = models.JSONField(default=list)       # ['xlsx','pdf','csv']
    required_permission = models.CharField(max_length=50)
    is_confidential = models.BooleanField(default=False)
    # Exposed on the paginated dataset pull API (/reports/datasets/{code}/) for
    # data-lake consumers, in addition to the file formats.
    is_dataset = models.BooleanField(default=False)

    class Meta:
        db_table = 'reports_definition'
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.code} ({self.category})'


class ReportExecution(BaseModel):
    """One generated report instance. Mirrors BulkJob's status shape so the
    frontend polls it the same way. The RBAC subtree is frozen in
    ``scope_snapshot`` at request time so a slow job cannot widen its own scope,
    and ``computation_refs`` link the numbers back to their ComputationLogs."""

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    class Format(models.TextChoices):
        XLSX = 'xlsx', 'Excel'
        PDF = 'pdf', 'PDF'
        CSV = 'csv', 'CSV'

    definition = models.ForeignKey(ReportDefinition, on_delete=models.PROTECT,
                                   related_name='executions')
    requested_by = models.ForeignKey('accounts.User', null=True, on_delete=models.SET_NULL,
                                     related_name='report_executions')
    parameters = models.JSONField(default=dict)
    scope_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.QUEUED, db_index=True)
    format = models.CharField(max_length=10, choices=Format.choices, default=Format.XLSX)
    row_count = models.PositiveIntegerField(default=0)
    file = models.FileField(upload_to=report_upload_path, max_length=500, null=True, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    error = models.TextField(blank=True, default='')
    computation_refs = models.JSONField(default=list)
    expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Outbound push (schedules with delivery='target').
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_error = models.TextField(blank=True, default='')

    TERMINAL_STATUSES = frozenset((Status.COMPLETED, Status.FAILED))

    class Meta:
        db_table = 'reports_execution'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['requested_by', '-created_at']),
            models.Index(fields=['definition', 'status']),
        ]

    def __str__(self):
        return f'{self.definition.code} #{self.pk} ({self.status})'

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES


class ReportSchedule(BaseModel):
    """A recurring report run, synced to a django-celery-beat PeriodicTask.
    ``parameters`` may hold relative tokens (period='current'|'last_month') that
    are resolved to concrete values at fire time. Each recipient receives the
    report generated in THEIR RBAC scope, so one schedule yields per-role views."""

    class Delivery(models.TextChoices):
        IN_APP = 'in_app', 'In-app'
        EMAIL = 'email', 'Email'
        BOTH = 'both', 'Both'
        TARGET = 'target', 'Delivery target (S3 / SFTP)'

    definition = models.ForeignKey(ReportDefinition, on_delete=models.PROTECT,
                                   related_name='schedules')
    name = models.CharField(max_length=120)
    parameters = models.JSONField(default=dict)
    format = models.CharField(max_length=10, choices=ReportExecution.Format.choices,
                              default=ReportExecution.Format.XLSX)

    # Crontab fields (django-celery-beat semantics).
    cron_minute = models.CharField(max_length=60, default='0')
    cron_hour = models.CharField(max_length=60, default='6')
    cron_day_of_week = models.CharField(max_length=60, default='*')
    cron_day_of_month = models.CharField(max_length=60, default='*')
    cron_month_of_year = models.CharField(max_length=60, default='*')

    # {"users": [ids], "roles": ["finance", ...], "entities": [ids]}
    recipients = models.JSONField(default=dict)
    delivery = models.CharField(max_length=10, choices=Delivery.choices, default=Delivery.BOTH)
    # Required when delivery='target': where the artifact is pushed. Target runs
    # generate ONE extract in the owner's RBAC scope (a machine feed, not per-user).
    delivery_target = models.ForeignKey(
        'reports.DeliveryTarget', null=True, blank=True, on_delete=models.PROTECT,
        related_name='schedules',
    )
    is_enabled = models.BooleanField(default=True, db_index=True)

    owner = models.ForeignKey('accounts.User', null=True, on_delete=models.SET_NULL,
                              related_name='report_schedules')
    periodic_task_id = models.BigIntegerField(null=True, blank=True)  # link to beat PeriodicTask
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'reports_schedule'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.definition.code})'


class DeliveryTarget(BaseModel):
    """An outbound destination for scheduled extracts (data lake, client SFTP).

    ``config`` holds the non-secret connection details; the secret itself is NEVER
    stored in the DB — ``credential_env`` names the environment variable holding it
    on this client's EC2 (per-client isolation makes env-based secrets acceptable).
      s3:   config = {bucket, prefix?, region?, access_key_id?}   secret = secret access key
      sftp: config = {host, port?, path?, username}               secret = password
    """

    S3 = 's3'
    SFTP = 'sftp'
    KIND_CHOICES = [(S3, 'Amazon S3'), (SFTP, 'SFTP')]

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    config = models.JSONField(default=dict)
    credential_env = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        db_table = 'reports_deliverytarget'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} ({self.kind})'
