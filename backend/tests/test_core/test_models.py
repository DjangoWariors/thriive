"""
Tests for BaseModel and VersionedMixin.
Uses an in-test concrete model created via schema_editor.
"""
from datetime import date, timedelta

import pytest
from django.db import connection, models

from apps.core.models import BaseModel, VersionedMixin


@pytest.fixture(scope='module')
def versioned_cls(django_db_setup, django_db_blocker):
    """
    Create a transient concrete table for VersionedMixin testing.
    Torn down after the module.
    """
    class ConcreteVersioned(VersionedMixin, BaseModel):
        code = models.CharField(max_length=50)
        name = models.CharField(max_length=200)

        class Meta:
            app_label = 'core'

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.create_model(ConcreteVersioned)

    yield ConcreteVersioned

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.delete_model(ConcreteVersioned)


@pytest.mark.django_db
def test_create_new_version(versioned_cls):
    """
    create_new_version must:
    - retire the old row (is_current=False, effective_to set)
    - insert a new row with version+1, is_current=True
    - accept field overrides
    """
    today = date.today()
    obj = versioned_cls.objects.create(
        code='KPI_001', name='Original', effective_from=today,
    )
    original_pk = obj.pk

    new_obj = obj.create_new_version(name='Updated')

    # Old row is retired
    old = versioned_cls.objects.get(pk=original_pk)
    assert old.is_current is False
    assert old.effective_to == today - timedelta(days=1)

    # New row is current
    assert new_obj.pk != original_pk
    assert new_obj.version == 2
    assert new_obj.is_current is True
    assert new_obj.effective_to is None
    assert new_obj.name == 'Updated'
    assert new_obj.code == 'KPI_001'

    # Exactly one current version
    assert versioned_cls.objects.filter(code='KPI_001', is_current=True).count() == 1
