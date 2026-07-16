"""
NodeService — 14 tests covering create, validation, move, deactivate.
"""
from datetime import date

import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Node, NodeType
from apps.hierarchy.services import NodeService


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(db):
    return User.objects.create_user(email='admin@example.com', password='adminpass')


@pytest.fixture
def base_type(db):
    """A simple non-loginable entity type with no parent restrictions."""
    return NodeType.objects.create(
        name='NSM', code='NSM', level_order=1, effective_from=date.today(),
    )


@pytest.fixture
def child_type(db, base_type):
    """Node type that must have an NSM parent."""
    return NodeType.objects.create(
        name='ASE', code='ASE', level_order=3, effective_from=date.today(),
        allowed_parent_types=['NSM'],
    )


@pytest.fixture
def loginable_type(db):
    """OTP-only loginable entity type with a required mobile attribute."""
    return NodeType.objects.create(
        name='Retailer', code='RETAILER', level_order=4,
        is_loginable=True,
        attribute_schema=[
            {
                'key': 'mobile', 'label': 'Mobile',
                'type': 'phone', 'required': True, 'unique': False,
            }
        ],
        display_config={'login_method': 'otp_only', 'portal_type': 'partner'},
        effective_from=date.today(),
    )


def _make(entity_type, code, parent=None, attributes=None, extra=None) -> dict:
    """Build a data dict for NodeService.create_entity."""
    d: dict = {
        'entity_type_id': entity_type.id,
        'name': f'{code} entity',
        'code': code,
        'attributes': attributes or {},
        'effective_from': date.today(),
    }
    if parent:
        d['parent_id'] = parent.id
    if extra:
        d.update(extra)
    return d


# ── 1. Basic create ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_entity_basic(base_type, admin_user):
    entity = NodeService.create_entity(_make(base_type, 'ROOT001'), admin_user)
    assert entity.pk is not None
    assert entity.path == '/ROOT001/'
    assert entity.depth == 0
    assert entity.is_current is True
    assert entity.version == 1


# ── 1b. Auto-generated code (blank code → {TYPE}-NNNN) ────────────────────────

@pytest.mark.django_db
def test_code_auto_generated_when_blank(child_type, base_type, admin_user):
    parent = NodeService.create_entity(_make(base_type, 'NSM1'), admin_user)
    e1 = NodeService.create_entity(
        {'entity_type_id': child_type.id, 'name': 'Priya', 'parent_id': parent.id},
        admin_user,
    )
    e2 = NodeService.create_entity(
        {'entity_type_id': child_type.id, 'name': 'Rahul', 'parent_id': parent.id},
        admin_user,
    )
    # Stable, geography-free, sequential per type — independent of the person's name.
    assert e1.code == 'ASE-0001'
    assert e2.code == 'ASE-0002'


@pytest.mark.django_db
def test_auto_code_continues_past_existing_max(child_type, base_type, admin_user):
    parent = NodeService.create_entity(_make(base_type, 'NSM1'), admin_user)
    NodeService.create_entity(_make(child_type, 'ASE-0005', parent=parent), admin_user)
    auto = NodeService.create_entity(
        {'entity_type_id': child_type.id, 'name': 'Next', 'parent_id': parent.id},
        admin_user,
    )
    assert auto.code == 'ASE-0006'


# ── 2. Loginable → auto-creates User ──────────────────────────────────────────

@pytest.mark.django_db
def test_create_loginable_auto_creates_user(loginable_type, admin_user):
    entity = NodeService.create_entity(
        _make(loginable_type, 'RET001', attributes={'mobile': '9876543210'}),
        admin_user,
    )
    linked = User.objects.get(entity=entity)
    assert linked.mobile == '9876543210'
    assert not linked.has_usable_password()
    assert linked.is_active is True


# ── 2a. Password-capable type → form password becomes the login password ──────

@pytest.fixture
def password_type(db):
    """Password+OTP loginable type with a required email attribute."""
    return NodeType.objects.create(
        name='XSE', code='XSE', level_order=4,
        is_loginable=True,
        attribute_schema=[
            {
                'key': 'email', 'label': 'Email',
                'type': 'email', 'required': True, 'unique': False,
            }
        ],
        display_config={'login_method': 'password_and_otp', 'portal_type': 'admin'},
        effective_from=date.today(),
    )


@pytest.mark.django_db
def test_create_with_password_sets_login_password(password_type, admin_user):
    entity = NodeService.create_entity(
        _make(password_type, 'XSE001', attributes={'email': 'anjali@test.com'},
              extra={'password': 'Test@1234'}),
        admin_user,
    )
    linked = User.objects.get(entity=entity)
    assert linked.check_password('Test@1234')


@pytest.mark.django_db
def test_create_without_password_leaves_it_settable_later(password_type, admin_user):
    entity = NodeService.create_entity(
        _make(password_type, 'XSE002', attributes={'email': 'ravi@test.com'}),
        admin_user,
    )
    assert not User.objects.get(entity=entity).has_usable_password()


@pytest.mark.django_db
def test_create_weak_password_rejected(password_type, admin_user):
    with pytest.raises(BusinessError):
        NodeService.create_entity(
            _make(password_type, 'XSE003', attributes={'email': 'weak@test.com'},
                  extra={'password': '123'}),
            admin_user,
        )
    assert not Node.objects.filter(code='XSE003').exists()


@pytest.mark.django_db
def test_otp_only_type_ignores_password(loginable_type, admin_user):
    entity = NodeService.create_entity(
        _make(loginable_type, 'RET009', attributes={'mobile': '9876500009'},
              extra={'password': 'Test@1234'}),
        admin_user,
    )
    assert not User.objects.get(entity=entity).has_usable_password()


@pytest.mark.django_db
def test_update_resets_password(password_type, admin_user):
    entity = NodeService.create_entity(
        _make(password_type, 'XSE004', attributes={'email': 'reset@test.com'},
              extra={'password': 'Test@1234'}),
        admin_user,
    )
    NodeService.update_entity(entity.pk, {'password': 'NewPass@5678'}, admin_user)
    assert User.objects.get(entity=entity).check_password('NewPass@5678')


# ── 2b. Duplicate login detail → clean BusinessError, not IntegrityError ──────

@pytest.mark.django_db
def test_duplicate_mobile_raises_business_error(loginable_type, admin_user):
    NodeService.create_entity(
        _make(loginable_type, 'RET001', attributes={'mobile': '9876543210'}),
        admin_user,
    )
    with pytest.raises(BusinessError, match="mobile '9876543210' already exists"):
        NodeService.create_entity(
            _make(loginable_type, 'RET002', attributes={'mobile': '9876543210'}),
            admin_user,
        )
    # The second entity must not be left behind by the rolled-back transaction.
    assert not Node.objects.filter(code='RET002').exists()


# ── 3. Non-loginable → no User created ────────────────────────────────────────

@pytest.mark.django_db
def test_create_non_loginable_no_user(base_type, admin_user):
    entity = NodeService.create_entity(_make(base_type, 'NSM001'), admin_user)
    assert not User.objects.filter(entity=entity).exists()


# ── 4. Invalid parent type rejected ───────────────────────────────────────────

@pytest.mark.django_db
def test_invalid_parent_type_rejected(child_type, admin_user):
    wrong_type = NodeType.objects.create(
        name='RSM', code='RSM', level_order=2, effective_from=date.today(),
    )
    wrong_parent = NodeService.create_entity(_make(wrong_type, 'RSM001'), admin_user)

    with pytest.raises(BusinessError, match='not allowed'):
        NodeService.create_entity(
            _make(child_type, 'ASE001', parent=wrong_parent),
            admin_user,
        )


# ── 5. Missing required attribute ─────────────────────────────────────────────

@pytest.mark.django_db
def test_missing_required_attribute(admin_user):
    et = NodeType.objects.create(
        name='ASE2', code='ASE2', level_order=3, effective_from=date.today(),
        attribute_schema=[
            {'key': 'employee_id', 'label': 'Employee ID',
             'type': 'string', 'required': True, 'unique': False},
        ],
    )
    with pytest.raises(BusinessError, match='Employee ID is required'):
        NodeService.create_entity(_make(et, 'E001', attributes={}), admin_user)


# ── 6. Unique attribute violation ─────────────────────────────────────────────

@pytest.mark.django_db
def test_unique_attribute_violation(admin_user):
    et = NodeType.objects.create(
        name='ASE3', code='ASE3', level_order=3, effective_from=date.today(),
        attribute_schema=[
            {'key': 'gst', 'label': 'GST Number',
             'type': 'string', 'required': True, 'unique': True},
        ],
    )
    NodeService.create_entity(_make(et, 'E001', attributes={'gst': 'GST12345'}), admin_user)

    with pytest.raises(BusinessError, match='already in use'):
        NodeService.create_entity(_make(et, 'E002', attributes={'gst': 'GST12345'}), admin_user)


# ── 7. Invalid choice attribute ───────────────────────────────────────────────

@pytest.mark.django_db
def test_invalid_choice_attribute(admin_user):
    et = NodeType.objects.create(
        name='STORE', code='STORE', level_order=4, effective_from=date.today(),
        attribute_schema=[
            {'key': 'store_class', 'label': 'Store Class',
             'type': 'choice', 'options': ['A', 'B', 'C'], 'required': True, 'unique': False},
        ],
    )
    with pytest.raises(BusinessError, match='must be one of'):
        NodeService.create_entity(
            _make(et, 'S001', attributes={'store_class': 'D'}),
            admin_user,
        )


# ── 8. Subtree query correct count ────────────────────────────────────────────

@pytest.mark.django_db
def test_subtree_query_correct_count(base_type, admin_user):
    # Use a single unrestricted type so we can form any tree shape freely.
    root = NodeService.create_entity(_make(base_type, 'R001'), admin_user)
    c1   = NodeService.create_entity(_make(base_type, 'C001', parent=root), admin_user)
    c2   = NodeService.create_entity(_make(base_type, 'C002', parent=root), admin_user)
    _gc  = NodeService.create_entity(_make(base_type, 'GC001', parent=c1), admin_user)

    subtree = root.get_subtree()
    assert subtree.count() == 3  # c1, c2, gc
    ids = set(subtree.values_list('id', flat=True))
    assert c1.pk in ids
    assert c2.pk in ids


# ── 9. Move updates entity path ────────────────────────────────────────────────

@pytest.mark.django_db
def test_move_updates_path(base_type, admin_user):
    parent_a = NodeService.create_entity(_make(base_type, 'A001'), admin_user)
    parent_b = NodeService.create_entity(_make(base_type, 'B001'), admin_user)
    child = NodeService.create_entity(_make(base_type, 'CHILD001', parent=parent_a), admin_user)

    assert child.path == '/A001/CHILD001/'

    moved = NodeService.move_entity(
        entity_id=child.pk,
        new_parent_id=parent_b.pk,
        reason='Restructure',
        effective_date=date.today(),
        user=admin_user,
    )
    assert moved.path == '/B001/CHILD001/'
    assert moved.depth == 1


# ── 10. Move updates descendant paths ─────────────────────────────────────────

@pytest.mark.django_db
def test_move_updates_descendant_paths(base_type, admin_user):
    old_parent = NodeService.create_entity(_make(base_type, 'OLD001'), admin_user)
    new_parent = NodeService.create_entity(_make(base_type, 'NEW001'), admin_user)
    mid = NodeService.create_entity(_make(base_type, 'MID001', parent=old_parent), admin_user)
    leaf = NodeService.create_entity(_make(base_type, 'LEAF001', parent=mid), admin_user)

    assert leaf.path == '/OLD001/MID001/LEAF001/'

    NodeService.move_entity(
        entity_id=mid.pk,
        new_parent_id=new_parent.pk,
        reason='Reorg',
        effective_date=date.today(),
        user=admin_user,
    )

    leaf.refresh_from_db()
    assert leaf.path == '/NEW001/MID001/LEAF001/'
    assert leaf.depth == 2


# ── 10b. Move query budget is independent of subtree size ────────────────────

@pytest.mark.django_db
def test_move_query_count_independent_of_subtree_size(base_type, admin_user):
    """A move must rewrite descendant paths in one set-based UPDATE, not load the
    subtree into Python. So moving a node above 3 descendants and one above 30
    must issue the *same* number of queries."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def build_and_move(prefix, width):
        dest = NodeService.create_entity(_make(base_type, f'{prefix}DEST'), admin_user)
        root = NodeService.create_entity(_make(base_type, f'{prefix}ROOT'), admin_user)
        for i in range(width):
            NodeService.create_entity(
                _make(base_type, f'{prefix}C{i:03d}', parent=root), admin_user,
            )
        with CaptureQueriesContext(connection) as ctx:
            NodeService.move_entity(
                entity_id=root.pk, new_parent_id=dest.pk,
                reason='budget', effective_date=date.today(), user=admin_user,
            )
        return len(ctx.captured_queries)

    small = build_and_move('S', 3)
    large = build_and_move('L', 30)
    assert small == large, f'move query count scaled with subtree size: {small} vs {large}'


# ── 11. Cannot move under self ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_cannot_move_under_self(base_type, admin_user):
    entity = NodeService.create_entity(_make(base_type, 'SELF001'), admin_user)
    with pytest.raises(BusinessError, match='own parent'):
        NodeService.move_entity(
            entity_id=entity.pk,
            new_parent_id=entity.pk,
            reason='Invalid',
            effective_date=date.today(),
            user=admin_user,
        )


# ── 12. Cannot move under own descendant ──────────────────────────────────────

@pytest.mark.django_db
def test_cannot_move_under_own_descendant(base_type, admin_user):
    parent = NodeService.create_entity(_make(base_type, 'PAR001'), admin_user)
    child = NodeService.create_entity(_make(base_type, 'CHD001', parent=parent), admin_user)

    with pytest.raises(BusinessError, match='descendants'):
        NodeService.move_entity(
            entity_id=parent.pk,
            new_parent_id=child.pk,
            reason='Invalid circular',
            effective_date=date.today(),
            user=admin_user,
        )


# ── 13. Move creates AuditLog with reason ─────────────────────────────────────

@pytest.mark.django_db
def test_move_audit_logged_with_reason(base_type, admin_user):
    src = NodeService.create_entity(_make(base_type, 'SRC001'), admin_user)
    dst = NodeService.create_entity(_make(base_type, 'DST001'), admin_user)
    child = NodeService.create_entity(_make(base_type, 'MOVED001', parent=src), admin_user)

    NodeService.move_entity(
        entity_id=child.pk,
        new_parent_id=dst.pk,
        reason='Annual restructure',
        effective_date=date.today(),
        user=admin_user,
    )

    log = AuditLog.objects.filter(
        entity_type='hierarchy.Node',
        entity_id=child.pk,
        action='move',
    ).latest('timestamp')

    assert log.changes['reason'] == 'Annual restructure'
    assert log.changes['parent_id'][1] == dst.pk
    assert log.user_id == admin_user.pk


# ── 14. Deactivate cascades to linked User ─────────────────────────────────────

@pytest.mark.django_db
def test_deactivate_cascades_to_user(loginable_type, admin_user):
    entity = NodeService.create_entity(
        _make(loginable_type, 'RET999', attributes={'mobile': '9000000001'}),
        admin_user,
    )
    linked = User.objects.get(entity=entity)
    assert linked.is_active is True

    NodeService.deactivate_entity(entity.pk, reason='Partner exited', user=admin_user)

    entity.refresh_from_db()
    linked.refresh_from_db()

    assert entity.status == 'inactive'
    assert linked.is_active is False


# ── update_entity ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_name_and_attributes_persist(loginable_type, admin_user):
    entity = NodeService.create_entity(
        _make(loginable_type, 'RET100', attributes={'mobile': '9000000001'}),
        admin_user,
    )
    NodeService.update_entity(
        entity.pk,
        {'name': 'Renamed Store', 'attributes': {'mobile': '9000000002'}},
        admin_user,
    )
    entity.refresh_from_db()
    assert entity.name == 'Renamed Store'
    assert entity.attributes['mobile'] == '9000000002'


@pytest.mark.django_db
def test_update_keeps_own_unique_attribute(admin_user):
    """Editing an entity must not flag its OWN unique attribute value as a duplicate."""
    et = NodeType.objects.create(
        name='DIST', code='DIST', level_order=3, effective_from=date.today(),
        attribute_schema=[
            {'key': 'gst', 'label': 'GST Number',
             'type': 'string', 'required': True, 'unique': True},
        ],
    )
    entity = NodeService.create_entity(
        _make(et, 'D001', attributes={'gst': 'GST99999'}), admin_user,
    )
    # Re-saving the same unique value (e.g. just renaming) must succeed.
    NodeService.update_entity(
        entity.pk,
        {'name': 'Renamed', 'attributes': {'gst': 'GST99999'}},
        admin_user,
    )
    entity.refresh_from_db()
    assert entity.name == 'Renamed'
    assert entity.attributes['gst'] == 'GST99999'

    # But colliding with ANOTHER entity's value must still be rejected.
    NodeService.create_entity(_make(et, 'D002', attributes={'gst': 'GST88888'}), admin_user)
    with pytest.raises(BusinessError, match='already in use'):
        NodeService.update_entity(entity.pk, {'attributes': {'gst': 'GST88888'}}, admin_user)


@pytest.mark.django_db
def test_update_invalid_attribute_rejected(loginable_type, admin_user):
    entity = NodeService.create_entity(
        _make(loginable_type, 'RET101', attributes={'mobile': '9000000003'}),
        admin_user,
    )
    with pytest.raises(BusinessError):
        # mobile is required → empty value must fail validation
        NodeService.update_entity(entity.pk, {'attributes': {'mobile': ''}}, admin_user)


@pytest.mark.django_db
def test_update_propagates_email_mobile_to_linked_user(loginable_type, admin_user):
    entity = NodeService.create_entity(
        _make(loginable_type, 'RET102', attributes={'mobile': '9000000004'}),
        admin_user,
    )
    NodeService.update_entity(
        entity.pk,
        {'email': 'store102@acme.com', 'mobile': '9111111111'},
        admin_user,
    )
    linked = User.objects.get(entity=entity)
    assert linked.email == 'store102@acme.com'
    assert linked.mobile == '9111111111'


@pytest.mark.django_db
def test_update_duplicate_email_rejected(loginable_type, admin_user):
    User.objects.create_user(email='taken@acme.com', password='x')
    entity = NodeService.create_entity(
        _make(loginable_type, 'RET103', attributes={'mobile': '9000000005'}),
        admin_user,
    )
    with pytest.raises(BusinessError):
        NodeService.update_entity(entity.pk, {'email': 'taken@acme.com'}, admin_user)


@pytest.mark.django_db
def test_update_does_not_change_code_or_path(base_type, admin_user):
    entity = NodeService.create_entity(_make(base_type, 'ROOT900'), admin_user)
    original_path = entity.path
    # 'code' is not an accepted field — even if passed it must be ignored.
    NodeService.update_entity(entity.pk, {'name': 'New Name', 'code': 'HACKED'}, admin_user)
    entity.refresh_from_db()
    assert entity.code == 'ROOT900'
    assert entity.path == original_path
