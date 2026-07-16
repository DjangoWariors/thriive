from datetime import date, timedelta

from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        abstract = True


class VersionedMixin(models.Model):
    version = models.PositiveIntegerField(default=1)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True, db_index=True)

    class Meta:
        abstract = True

    def create_new_version(self, **override_fields):
        """
        Retire self in-place, then INSERT a new row with version+1.
        Returns self (now pointing at the new DB row).
        """
        old_pk = self.pk
        old_version = self.version
        today = date.today()

        # Retire the current row without touching the Python object yet
        type(self).objects.filter(pk=old_pk).update(
            is_current=False,
            effective_to=today - timedelta(days=1),
        )

        # Reuse same Python object: clear PK so Django does an INSERT
        self.pk = None
        self.version = old_version + 1
        self.effective_from = today
        self.effective_to = None
        self.is_current = True
        for key, val in override_fields.items():
            setattr(self, key, val)
        self.save()
        return self
