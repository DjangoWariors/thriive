from django.contrib import admin

from .models import Assignment


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'assignee', 'scope', 'role_in_scope', 'effective_from', 'effective_to')
    list_filter = ('role_in_scope', 'is_active')
    search_fields = ('assignee__code', 'assignee__name', 'scope__code', 'scope__name')
