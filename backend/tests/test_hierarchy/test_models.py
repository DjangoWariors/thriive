"""
Hierarchy model tests — path computation, subtree, ancestors, geography.
"""
from datetime import date

import pytest

from apps.hierarchy.models import (
    Channel,
    Node,
    NodeType,
    GeographyNode,
    GeographyType,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def channel(db):
    return Channel.objects.create(name='General Trade', code='GT')


@pytest.fixture
def entity_type(db):
    return NodeType.objects.create(
        name='National Sales Manager',
        code='NSM',
        level_order=1,
        effective_from=date.today(),
    )


@pytest.fixture
def root(db, entity_type):
    return Node.objects.create(
        entity_type=entity_type,
        name='Root',
        code='ROOT001',
        effective_from=date.today(),
    )


@pytest.fixture
def child(db, entity_type, root):
    return Node.objects.create(
        entity_type=entity_type,
        name='Child',
        code='CHILD001',
        parent=root,
        effective_from=date.today(),
    )


@pytest.fixture
def grandchild(db, entity_type, child):
    return Node.objects.create(
        entity_type=entity_type,
        name='Grandchild',
        code='GC001',
        parent=child,
        effective_from=date.today(),
    )


@pytest.fixture
def sibling(db, entity_type, root):
    return Node.objects.create(
        entity_type=entity_type,
        name='Sibling',
        code='SIB001',
        parent=root,
        effective_from=date.today(),
    )


# ── Path computation ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_root_entity_path_and_depth(root):
    assert root.path == '/ROOT001/'
    assert root.depth == 0


@pytest.mark.django_db
def test_child_path_includes_parent_segment(child, root):
    assert child.path == f'{root.path}CHILD001/'
    assert child.path == '/ROOT001/CHILD001/'
    assert child.depth == 1


@pytest.mark.django_db
def test_grandchild_path_is_full_lineage(grandchild):
    assert grandchild.path == '/ROOT001/CHILD001/GC001/'
    assert grandchild.depth == 2


# ── get_subtree ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_subtree_contains_all_descendants(root, child, grandchild):
    ids = set(root.get_subtree().values_list('id', flat=True))
    assert child.id in ids
    assert grandchild.id in ids


@pytest.mark.django_db
def test_get_subtree_excludes_self(root, child):
    subtree = root.get_subtree()
    assert not subtree.filter(pk=root.pk).exists()


@pytest.mark.django_db
def test_get_subtree_of_leaf_is_empty(grandchild):
    assert grandchild.get_subtree().count() == 0


# ── get_ancestors ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_ancestors_walks_to_root(grandchild, child, root):
    ancestors = grandchild.get_ancestors()
    ancestor_ids = [e.id for e in ancestors]
    assert child.id in ancestor_ids
    assert root.id in ancestor_ids


@pytest.mark.django_db
def test_get_ancestors_parent_first_ordering(grandchild, child, root):
    ancestors = grandchild.get_ancestors()
    assert ancestors[0].id == child.id
    assert ancestors[1].id == root.id


@pytest.mark.django_db
def test_root_has_no_ancestors(root):
    assert root.get_ancestors() == []


@pytest.mark.django_db
def test_child_has_one_ancestor(child, root):
    ancestors = child.get_ancestors()
    assert len(ancestors) == 1
    assert ancestors[0].id == root.id


# ── get_direct_children ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_direct_children_returns_immediate_children_only(root, child, grandchild):
    children = list(root.get_direct_children())
    child_ids = [e.id for e in children]
    assert child.id in child_ids
    assert grandchild.id not in child_ids


@pytest.mark.django_db
def test_get_direct_children_excludes_inactive(root, entity_type):
    inactive = Node.objects.create(
        entity_type=entity_type,
        name='Inactive child',
        code='INACT001',
        parent=root,
        effective_from=date.today(),
        is_active=False,
    )
    child_ids = list(root.get_direct_children().values_list('id', flat=True))
    assert inactive.id not in child_ids


# ── get_siblings ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_siblings_returns_same_parent_children_excluding_self(child, sibling):
    sibling_ids = set(child.get_siblings().values_list('id', flat=True))
    assert sibling.id in sibling_ids
    assert child.id not in sibling_ids


@pytest.mark.django_db
def test_root_has_no_siblings(root):
    assert root.get_siblings().count() == 0


# ── get_team ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_team_without_filter_returns_all_descendants(root, child, grandchild):
    team_ids = set(root.get_team().values_list('id', flat=True))
    assert child.id in team_ids
    assert grandchild.id in team_ids


@pytest.mark.django_db
def test_get_team_with_type_filter(root, child, grandchild, entity_type):
    other_type = NodeType.objects.create(
        name='RSM', code='RSM', level_order=2, effective_from=date.today(),
    )
    Node.objects.filter(pk=grandchild.pk).update(entity_type=other_type)

    # Filter to only NSM entities
    team = root.get_team(entity_type_codes=['NSM'])
    ids = set(team.values_list('id', flat=True))
    assert child.id in ids
    assert grandchild.id not in ids


# ── GeographyNode path ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_geography_node_root_path_and_depth():
    geo_type = GeographyType.objects.create(name='Sales Geo', code='SALES_GEO')
    node = GeographyNode.objects.create(
        geography_type=geo_type,
        name='India',
        code='IND',
        level='country',
    )
    assert node.path == '/IND/'
    assert node.depth == 0


@pytest.mark.django_db
def test_geography_node_child_includes_parent_in_path():
    geo_type = GeographyType.objects.create(name='Sales Geo 2', code='SALES_GEO2')
    parent = GeographyNode.objects.create(
        geography_type=geo_type, name='India', code='IND2', level='country',
    )
    child = GeographyNode.objects.create(
        geography_type=geo_type, name='North', code='NORTH', level='region', parent=parent,
    )
    assert child.path == '/IND2/NORTH/'
    assert child.depth == 1


@pytest.mark.django_db
def test_geography_node_deep_path():
    geo_type = GeographyType.objects.create(name='Sales Geo 3', code='SALES_GEO3')
    country = GeographyNode.objects.create(
        geography_type=geo_type, name='India', code='IND3', level='country',
    )
    region = GeographyNode.objects.create(
        geography_type=geo_type, name='North', code='NORTH3', level='region', parent=country,
    )
    territory = GeographyNode.objects.create(
        geography_type=geo_type, name='Delhi', code='DL', level='territory', parent=region,
    )
    assert territory.path == '/IND3/NORTH3/DL/'
    assert territory.depth == 2


# ── Legacy guard ───────────────────────────────────────────────────────────────

def test_node_has_no_geography_fk():
    """Territory coverage is resolved ONLY through assignments.Assignment.
    The legacy Node.geography_node compat FK was removed (see
    docs/NETWORK_PEOPLE_SIMPLIFICATION_PLAN.md) — this guard keeps it out."""
    field_names = {f.name for f in Node._meta.get_fields()}
    assert 'geography_node' not in field_names
