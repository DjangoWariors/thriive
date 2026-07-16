from django.contrib import admin

from .models import (
    ApprovalDelegation, WorkflowAction, WorkflowDefinition, WorkflowInstance, WorkflowStep,
)


@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'subject_type', 'version', 'is_current', 'is_active')
    list_filter = ('subject_type', 'is_current', 'is_active')
    search_fields = ('code', 'name')


class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 0


class WorkflowActionInline(admin.TabularInline):
    model = WorkflowAction
    extra = 0


@admin.register(WorkflowInstance)
class WorkflowInstanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'definition', 'subject_type', 'subject_id', 'status',
                    'current_step', 'sla_due_at')
    list_filter = ('status', 'subject_type')
    inlines = [WorkflowStepInline, WorkflowActionInline]


@admin.register(ApprovalDelegation)
class ApprovalDelegationAdmin(admin.ModelAdmin):
    list_display = ('delegator', 'delegate', 'scope', 'start_date', 'end_date', 'is_active')
    list_filter = ('is_active',)
