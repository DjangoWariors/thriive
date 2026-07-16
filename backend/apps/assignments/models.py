from django.db import models

from apps.core.models import BaseModel


class Assignment(BaseModel):
    """Effective-dated bridge between the two trees.

    The geography tree (where the work lives) and the organisation tree (who does
    the work) never reference each other directly. An ``Assignment`` is the only
    link: it records that an organisation-tree entity (a person/position) owns a
    geography scope (a territory) for a period of time.

    When a person moves, the territory, its outlets and its targets stay put —
    only the assignment changes (see ``AssignmentService.transfer``). Visibility,
    achievement attribution and payout ownership all resolve through assignments
    rather than through a static FK on the entity.
    """

    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        STAND_IN = 'stand_in', 'Stand-in'
        SUPERVISOR = 'supervisor', 'Supervisor'

    assignee = models.ForeignKey(
        'hierarchy.Node',
        on_delete=models.PROTECT,
        related_name='assignments',
    )
    scope = models.ForeignKey(
        'hierarchy.GeographyNode',
        on_delete=models.PROTECT,
        related_name='assignments',
    )
    role_in_scope = models.CharField(
        max_length=20, choices=Role.choices, default=Role.OWNER,
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        db_table = 'assignments_assignment'
        indexes = [
            models.Index(fields=['scope', 'role_in_scope', 'effective_from'],
                         name='assign_scope_role_from_idx'),
            models.Index(fields=['assignee', 'effective_from'],
                         name='assign_assignee_from_idx'),
        ]

    def __str__(self):
        return f'{self.assignee} {self.role_in_scope} of {self.scope} (from {self.effective_from})'
