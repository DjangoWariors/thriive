"""Assignment bridge — effective-dated link between geography and organisation trees.

These prove the two-tree contract: a territory has at most one owner at a time,
ownership is resolved "as of" a date, transferring ownership leaves the geography
untouched, and visibility (scopes_owned_by) flips on the effective date.
"""
from datetime import date, timedelta

import pytest

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.audit.models import AuditLog
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType

TODAY = date.today()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email='root@example.com', password='pass')


@pytest.fixture
def people(db):
    """Two org-tree people (ASMs) who can hold a territory."""
    asm = NodeType.objects.create(
        name='ASM', code='ASM', level_order=1, effective_from=TODAY, is_loginable=True,
    )
    priya = Node.objects.create(entity_type=asm, name='Priya', code='ASM_PRIYA', effective_from=TODAY)
    rahul = Node.objects.create(entity_type=asm, name='Rahul', code='ASM_RAHUL', effective_from=TODAY)
    priya_user = User.objects.create_user(email='priya@x.com')
    priya_user.entity = priya
    priya_user.save(update_fields=['entity'])
    rahul_user = User.objects.create_user(email='rahul@x.com')
    rahul_user.entity = rahul
    rahul_user.save(update_fields=['entity'])
    return {'priya': priya, 'rahul': rahul, 'priya_user': priya_user, 'rahul_user': rahul_user}


@pytest.fixture
def territory(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'city'])
    north = GeographyNode.objects.create(geography_type=gt, name='North', code='NORTH', level='region')
    delhi = GeographyNode.objects.create(geography_type=gt, name='Delhi', code='DELHI', level='city', parent=north)
    return {'north': north, 'delhi': delhi}


@pytest.mark.django_db
class TestOwnership:

    def test_create_then_owner_of(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        owner = AssignmentService.owner_of(territory['delhi'].id)
        assert owner is not None and owner.id == people['priya'].id

    def test_unowned_scope_returns_none(self, territory):
        assert AssignmentService.owner_of(territory['delhi'].id) is None

    def test_owner_of_accepts_node_instance(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        assert AssignmentService.owner_of(territory['delhi']).id == people['priya'].id

    def test_double_owner_rejected(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        with pytest.raises(BusinessError, match='already has an owner'):
            AssignmentService.create(
                assignee_id=people['rahul'].id, scope_id=territory['delhi'].id,
                effective_from=TODAY, user=admin_user,
            )

    def test_as_of_date_respects_window(self, people, territory, admin_user):
        future = TODAY + timedelta(days=10)
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=future, user=admin_user,
        )
        # Not owned yet today; owned on the future date.
        assert AssignmentService.owner_of(territory['delhi'].id, on=TODAY) is None
        assert AssignmentService.owner_of(territory['delhi'].id, on=future).id == people['priya'].id


@pytest.mark.django_db
class TestTransfer:

    def test_transfer_flips_ownership_on_effective_date(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        handover = TODAY + timedelta(days=5)
        AssignmentService.transfer(
            scope_id=territory['delhi'].id, new_assignee_id=people['rahul'].id,
            effective_from=handover, reason='Priya promoted', user=admin_user,
        )
        # Day before handover → still Priya; on handover → Rahul.
        assert AssignmentService.owner_of(territory['delhi'].id, on=handover - timedelta(days=1)).id == people['priya'].id
        assert AssignmentService.owner_of(territory['delhi'].id, on=handover).id == people['rahul'].id

    def test_transfer_leaves_geography_untouched(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        AssignmentService.transfer(
            scope_id=territory['delhi'].id, new_assignee_id=people['rahul'].id,
            effective_from=TODAY + timedelta(days=1), user=admin_user,
        )
        node = GeographyNode.objects.get(pk=territory['delhi'].id)
        assert node.path == '/NORTH/DELHI/'  # territory unchanged by the handover

    def test_transfer_to_current_holder_rejected(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        with pytest.raises(BusinessError, match='already held'):
            AssignmentService.transfer(
                scope_id=territory['delhi'].id, new_assignee_id=people['priya'].id,
                effective_from=TODAY + timedelta(days=1), user=admin_user,
            )

    def test_transfer_audited(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        AssignmentService.transfer(
            scope_id=territory['delhi'].id, new_assignee_id=people['rahul'].id,
            effective_from=TODAY + timedelta(days=1), user=admin_user,
        )
        log = AuditLog.objects.filter(action='transfer', entity_type='assignments.Assignment').latest('id')
        assert log.changes['from_assignee_id'] == people['priya'].id
        assert log.changes['to_assignee_id'] == people['rahul'].id


@pytest.mark.django_db
class TestScopesOwnedBy:

    def test_user_sees_owned_territory(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        owned = AssignmentService.scopes_owned_by(people['priya_user'])
        assert list(owned.values_list('id', flat=True)) == [territory['delhi'].id]

    def test_visibility_flips_on_transfer(self, people, territory, admin_user):
        AssignmentService.create(
            assignee_id=people['priya'].id, scope_id=territory['delhi'].id,
            effective_from=TODAY, user=admin_user,
        )
        handover = TODAY + timedelta(days=3)
        AssignmentService.transfer(
            scope_id=territory['delhi'].id, new_assignee_id=people['rahul'].id,
            effective_from=handover, user=admin_user,
        )
        # Before handover Priya sees it; after, Rahul does and Priya doesn't.
        assert AssignmentService.scopes_owned_by(people['priya_user'], on=handover - timedelta(days=1)).exists()
        assert not AssignmentService.scopes_owned_by(people['priya_user'], on=handover).exists()
        assert AssignmentService.scopes_owned_by(people['rahul_user'], on=handover).exists()

    def test_unplaced_user_owns_nothing(self, db, territory):
        loner = User.objects.create_user(email='loner@x.com')
        assert not AssignmentService.scopes_owned_by(loner).exists()
