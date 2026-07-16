from django.db import models

from apps.core.models import BaseModel


class AuditLog(models.Model):
    """
    Immutable record of every business-critical mutation.
    Written by AuditService.log() from service-layer code.
    Never updated or deleted.

    Tamper-evidence: each row is hash-chained to its predecessor. ``row_hash``
    is sha256 over (prev_hash + action + entity_type + entity_id + user_id +
    changes). Editing any historical row changes its row_hash, which no longer
    matches the prev_hash stored on the following row — AuditService.verify_chain
    reports the first break. Appends are serialized through AuditChainHead so the
    chain never forks (see services.py).
    """
    action = models.CharField(max_length=50, db_index=True)   # create, update, move, deactivate, …
    entity_type = models.CharField(max_length=200, db_index=True)  # 'hierarchy.Node'
    entity_id = models.BigIntegerField(db_index=True)
    user_id = models.BigIntegerField(null=True, db_index=True)  # acting user; null for system tasks
    changes = models.JSONField(default=dict)
    prev_hash = models.CharField(max_length=64, blank=True, default='')
    row_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_auditlog'
        indexes = [
            models.Index(fields=['entity_type', 'entity_id', 'timestamp'],
                         name='audit_log_entity_ts_idx'),
            models.Index(fields=['user_id', 'timestamp'], name='audit_log_user_ts_idx'),
        ]

    def __str__(self):
        return f'[{self.action}] {self.entity_type}#{self.entity_id} by user {self.user_id}'


class AuditChainHead(models.Model):
    """
    Single-row pointer to the last AuditLog's row_hash. Locked with
    select_for_update on every append so the hash chain is strictly serialized
    (no forks) and remains DB-portable. Audit writes are not a hot path relative
    to reads/computations, so the per-append lock is an acceptable trade-off for
    a verifiable chain.
    """
    last_hash = models.CharField(max_length=64, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'audit_chainhead'


class AccessLog(models.Model):
    """
    Disclosure trail for confidential reads (payouts, variable pay
    registers). Answers "who looked at whose money". Append-only.
    """
    user_id = models.BigIntegerField(null=True, db_index=True)
    resource = models.CharField(max_length=50, db_index=True)   # payout, payout_register, …
    object_id = models.BigIntegerField(null=True)               # the row viewed, if applicable
    subject_entity_id = models.BigIntegerField(null=True, db_index=True)  # whose data was disclosed
    action = models.CharField(max_length=20, default='view')    # view, export, download
    request_id = models.CharField(max_length=64, blank=True)
    ip_address = models.CharField(max_length=64, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_accesslog'
        indexes = [
            models.Index(fields=['resource', 'timestamp'], name='audit_access_res_ts_idx'),
            models.Index(fields=['subject_entity_id', 'timestamp'],
                         name='audit_access_subj_ts_idx'),
        ]

    def __str__(self):
        return f'[{self.action}] {self.resource} by user {self.user_id}'


class ComputationLog(models.Model):
    """
    Audit trail for payout / achievement computations.
    Stores a snapshot of all config used so results can be reproduced later.
    """
    computation_type = models.CharField(max_length=50, db_index=True)  # payout, achievement
    entity_id = models.BigIntegerField(db_index=True)
    period_id = models.BigIntegerField(null=True)
    triggered_by_id = models.BigIntegerField(null=True)  # user_id or null for scheduled tasks
    config_snapshot = models.JSONField(default=dict)
    result_snapshot = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_computationlog'
        indexes = [
            models.Index(fields=['entity_id', 'computation_type'],
                         name='audit_comp_entity_type_idx'),
            models.Index(fields=['timestamp'], name='audit_comp_ts_idx'),
        ]

    def __str__(self):
        return f'[{self.computation_type}] entity {self.entity_id} @ {self.timestamp}'


class RetentionPolicy(BaseModel):
    """
    Per-log-type retention window. A beat-scheduled sweep (tasks.sweep_retention)
    deletes rows older than ``retain_days``. Statutory windows differ by client
    and log type, so this is configuration, never hardcoded.
    """

    class LogType(models.TextChoices):
        AUDIT = 'audit', 'Audit Log'
        ACCESS = 'access', 'Access Log'
        COMPUTATION = 'computation', 'Computation Log'
        REPORT_ARTIFACT = 'report_artifact', 'Report Artifact'

    log_type = models.CharField(max_length=30, choices=LogType.choices, unique=True)
    retain_days = models.PositiveIntegerField()
    archive_strategy = models.CharField(max_length=20, default='delete')  # delete | archive | cold

    class Meta:
        db_table = 'audit_retentionpolicy'

    def __str__(self):
        return f'{self.log_type}: {self.retain_days}d ({self.archive_strategy})'
