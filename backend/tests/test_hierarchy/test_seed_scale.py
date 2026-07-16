"""seed_scale --geography/--assign builds both trees + the ownership bridge."""
from datetime import date

import pytest
from django.core.management import call_command

from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Channel, GeographyNode, Node, NodeType

TODAY = date.today()


@pytest.fixture
def scale_types(db):
    Channel.objects.create(code='GT', name='General Trade')
    for i, code in enumerate(['nsm', 'rsm', 'asm', 'ase', 'distributor', 'retailer'], start=1):
        NodeType.objects.create(name=code.upper(), code=code, level_order=i, effective_from=TODAY)


@pytest.mark.django_db
def test_seed_scale_builds_both_trees_and_bridge(scale_types):
    call_command(
        'seed_scale', total=60, rsm=1, asm_per=1, ase_per=2, dist_per=2,
        geography=60, assign=True, batch=50,
    )

    retailers = Node.objects.filter(code__startswith='SCALE-RET-')
    outlets = GeographyNode.objects.filter(code__startswith='SCALE-GEO-OUT-')
    assert retailers.exists() and outlets.exists()

    # Managers own the upper levels; retailers own outlets 1:1.
    nation = GeographyNode.objects.get(code='SCALE-GEO-NAT-0000001')
    nsm = Node.objects.get(code='SCALE-NSM-0000001')
    assert AssignmentService.owner_of(nation).pk == nsm.pk

    pairs = min(retailers.count(), outlets.count())
    retailer_assignments = Assignment.objects.filter(
        assignee__code__startswith='SCALE-RET-', role_in_scope='owner')
    assert retailer_assignments.count() == pairs

    # The batched resolver sees each retailer's outlet subtree.
    some = list(retailers.values_list('id', flat=True)[:5])
    owned = AssignmentService.scope_node_ids_map(some)
    assert all(len(v) >= 1 for v in owned.values())

    # Purge removes the whole batch — assignments, territories, entities.
    call_command('seed_scale', total=10, rsm=1, asm_per=1, ase_per=1, dist_per=1,
                 purge=True, batch=50)
    assert not Assignment.objects.filter(scope__code__startswith='SCALE-GEO-').exists()
    assert not GeographyNode.objects.filter(code__startswith='SCALE-GEO-').exists()
