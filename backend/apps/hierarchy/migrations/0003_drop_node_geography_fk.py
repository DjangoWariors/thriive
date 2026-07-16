"""Remove the legacy Node.geography_node compat FK.

Territory coverage is resolved exclusively through assignments.Assignment.
Before dropping the column, any node whose FK points at a scope with no open
owner is backfilled with a real owner Assignment (first claimant wins — the
same rule seed data used). Stale FKs on already-owned scopes are discarded:
the assignment was the source of truth by definition.

Irreversible by design — the legacy column is not coming back.
"""
from django.db import migrations


def backfill_assignments(apps, schema_editor):
    from datetime import date

    from django.db.models import Q

    Node = apps.get_model('hierarchy', 'Node')
    Assignment = apps.get_model('assignments', 'Assignment')

    owned_scope_ids = set(
        Assignment.objects.filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=date.today()),
            role_in_scope='owner', is_active=True,
        ).values_list('scope_id', flat=True)
    )

    pinned = (
        Node.objects
        .filter(geography_node__isnull=False, is_current=True, is_active=True)
        .order_by('pk')
        .values('pk', 'geography_node_id', 'effective_from', 'created_at')
    )
    to_create = []
    for row in pinned:
        scope_id = row['geography_node_id']
        if scope_id in owned_scope_ids:
            continue
        owned_scope_ids.add(scope_id)
        to_create.append(Assignment(
            assignee_id=row['pk'],
            scope_id=scope_id,
            role_in_scope='owner',
            effective_from=row['effective_from'] or row['created_at'].date(),
            reason='backfill: legacy geography_node FK',
        ))
    Assignment.objects.bulk_create(to_create)


class Migration(migrations.Migration):

    dependencies = [
        ('hierarchy', '0002_remove_nodetype_loyalty_eligible'),
        ('assignments', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_assignments, migrations.RunPython.noop),
        migrations.RemoveField(model_name='node', name='geography_node'),
    ]
