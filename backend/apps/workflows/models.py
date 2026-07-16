"""Generic, configurable multi-step approval workflow.

The engine knows nothing about incentives (or any other domain). A domain plugs in
by registering a ``SubjectAdapter`` (see ``adapters.py``) keyed by ``subject_type`` —
a dotted model label such as ``incentives.PayoutException``. An instance links to its
domain object by ``(subject_type, subject_id)`` (a soft pointer, like ``Transaction.entity_id``),
so the engine never imports the domain app.
"""
from django.db import models

from apps.core.models import BaseModel, VersionedMixin


class WorkflowDefinition(BaseModel, VersionedMixin):
    """A versioned approval template. ``steps`` is an ordered list of step configs::

        {"order": 1, "name": "Area Manager Review",
         "assignee_rule": "hierarchy_manager",   # | role | fixed_entity | initiator_manager
         "hierarchy_levels_up": 1, "role_code": null, "entity_code": null,
         "approval_mode": "single",              # | all | any
         "condition": {"field": "impact_amount", "op": "gt", "value": "50000"} | null,
         "sla_hours": 48, "on_sla_breach": "escalate"}   # | auto_approve | notify_only
    """

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=80)
    description = models.TextField(blank=True, default='')
    # Dotted model label of the governed domain object, e.g. 'incentives.PayoutException'.
    subject_type = models.CharField(max_length=100)
    trigger_event = models.CharField(max_length=80, blank=True, default='')
    steps = models.JSONField(default=list)

    class Meta:
        db_table = 'workflows_definition'
        ordering = ['code', '-version']
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='wf_def_code_ver_uniq'),
        ]
        indexes = [
            models.Index(fields=['subject_type', 'is_current'], name='wf_def_subj_cur_idx'),
            models.Index(fields=['code', 'is_current'], name='wf_def_code_cur_idx'),
        ]

    def __str__(self):
        return f'{self.code} v{self.version}'


class WorkflowInstance(BaseModel):
    """One running (or resolved) approval of a single domain object."""

    PENDING = 'pending'
    IN_REVIEW = 'in_review'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    ESCALATED = 'escalated'
    AUTO_APPROVED = 'auto_approved'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (PENDING, 'Pending'), (IN_REVIEW, 'In review'), (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'), (ESCALATED, 'Escalated'),
        (AUTO_APPROVED, 'Auto-approved'), (CANCELLED, 'Cancelled'),
    ]
    # Open = still needs someone to act.
    OPEN_STATUSES = (PENDING, IN_REVIEW, ESCALATED)
    TERMINAL_STATUSES = (APPROVED, REJECTED, AUTO_APPROVED, CANCELLED)

    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.PROTECT, related_name='instances',
    )
    subject_type = models.CharField(max_length=100, db_index=True)
    subject_id = models.BigIntegerField()
    initiated_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    # Routing origin — the subject's entity (managers above it become approvers).
    anchor_entity = models.ForeignKey(
        'hierarchy.Node', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='workflow_instances',
    )
    current_step = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True,
    )
    # Frozen snapshot used for conditional routing + inbox display.
    context_data = models.JSONField(default=dict, blank=True)
    sla_due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workflows_instance'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'sla_due_at'], name='wf_inst_status_sla_idx'),
            models.Index(fields=['subject_type', 'subject_id'], name='wf_inst_subject_idx'),
        ]

    def __str__(self):
        return f'WF#{self.pk} {self.subject_type}#{self.subject_id} ({self.status})'


class WorkflowStep(BaseModel):
    """A materialized (non-skipped) step in an instance's chain. Holds the resolved
    assignee(s) and SLA so the stepper + inbox render without recomputation."""

    PENDING = 'pending'
    ACTIVE = 'active'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    SKIPPED = 'skipped'
    ESCALATED = 'escalated'
    AUTO_APPROVED = 'auto_approved'
    STATUS_CHOICES = [
        (PENDING, 'Pending'), (ACTIVE, 'Active'), (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'), (SKIPPED, 'Skipped'), (ESCALATED, 'Escalated'),
        (AUTO_APPROVED, 'Auto-approved'),
    ]
    OPEN_STATUSES = (ACTIVE, ESCALATED)

    workflow = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveIntegerField()
    name = models.CharField(max_length=150)
    approval_mode = models.CharField(max_length=10, default='single')
    condition = models.JSONField(null=True, blank=True)
    # Raw step config, kept so assignees can be re-resolved at activation (honoring
    # transfers/delegations created after the instance was raised).
    config = models.JSONField(default=dict, blank=True)
    assignee_user = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    assignee_role_code = models.CharField(max_length=80, blank=True, default='')
    assignee_entity = models.ForeignKey(
        'hierarchy.Node', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    # All users eligible to action this step (role/parallel steps have several).
    assignee_user_ids = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    sla_due_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workflows_step'
        ordering = ['workflow_id', 'order']
        indexes = [
            models.Index(fields=['status'], name='wf_step_status_idx'),
        ]

    def __str__(self):
        return f'WF#{self.workflow_id} step {self.order} {self.name} ({self.status})'


class WorkflowAction(BaseModel):
    """Immutable audit timeline entry — one per human/system action."""

    INITIATE = 'initiate'
    APPROVE = 'approve'
    REJECT = 'reject'
    ESCALATE = 'escalate'
    COMMENT = 'comment'
    DELEGATE = 'delegate'
    REASSIGN = 'reassign'
    AUTO_APPROVE = 'auto_approve'
    ACTION_CHOICES = [
        (INITIATE, 'Initiate'), (APPROVE, 'Approve'), (REJECT, 'Reject'),
        (ESCALATE, 'Escalate'), (COMMENT, 'Comment'), (DELEGATE, 'Delegate'),
        (REASSIGN, 'Reassign'), (AUTO_APPROVE, 'Auto-approve'),
    ]

    workflow = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name='actions')
    step = models.ForeignKey(
        WorkflowStep, null=True, blank=True, on_delete=models.SET_NULL, related_name='actions',
    )
    step_order = models.PositiveIntegerField(default=0)
    action_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    action = models.CharField(max_length=15, choices=ACTION_CHOICES)
    comments = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'workflows_action'
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'WF#{self.workflow_id} {self.action} by {self.action_by_id}'


class ApprovalDelegation(BaseModel):
    """Out-of-office: ``delegate`` may act on ``delegator``'s steps within the window.
    ``scope`` is a workflow definition code or ``'all'``."""

    delegator = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='delegations_given',
    )
    delegate = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='delegations_received',
    )
    scope = models.CharField(max_length=80, blank=True, default='all')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'workflows_delegation'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['delegate', 'start_date', 'end_date'], name='wf_deleg_delegate_idx'),
            models.Index(fields=['delegator', 'start_date', 'end_date'], name='wf_deleg_delegator_idx'),
        ]

    def __str__(self):
        return f'{self.delegator_id}→{self.delegate_id} ({self.start_date}..{self.end_date})'
