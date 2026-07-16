from django.contrib import admin

from .models import (
    AllocationRecipe,
    PlanKpi,
    PlanRun,
    RevisionPolicy,
    ReviewTask,
    RunAllocation,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
    TargetRevision,
)


@admin.register(TargetPeriod)
class TargetPeriodAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'period_type', 'fiscal_year', 'start_date', 'end_date', 'status', 'parent')
    list_filter = ('period_type', 'status', 'fiscal_year')
    search_fields = ('code', 'name')


@admin.register(TargetPlan)
class TargetPlanAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'period', 'root_geography', 'channel', 'status', 'owner')
    list_filter = ('status',)
    search_fields = ('code', 'name')
    raw_id_fields = ('period', 'root_geography', 'channel', 'owner')


@admin.register(PlanKpi)
class PlanKpiAdmin(admin.ModelAdmin):
    list_display = ('id', 'plan', 'kpi', 'recipe', 'top_value', 'derived_top_value')
    raw_id_fields = ('plan', 'kpi', 'recipe')


@admin.register(PlanRun)
class PlanRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'plan', 'kind', 'status', 'scope_node', 'committed_by', 'committed_at', 'created_at')
    list_filter = ('kind', 'status')
    raw_id_fields = ('plan', 'scope_node', 'job', 'committed_by')


@admin.register(RunAllocation)
class RunAllocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'kpi', 'target_period', 'geography_node', 'channel',
                    'sku_group', 'value', 'base_value')
    search_fields = ('geography_node__code', 'kpi__code')
    raw_id_fields = ('run', 'kpi', 'target_period', 'geography_node', 'channel', 'sku_group')


@admin.register(ReviewTask)
class ReviewTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'plan', 'node', 'owner_node', 'status', 'submitted_by', 'submitted_at')
    list_filter = ('status',)
    raw_id_fields = ('plan', 'node', 'owner_node', 'submitted_by')


@admin.register(TargetAllocation)
class TargetAllocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'target_period', 'kpi', 'geography_node', 'effective_target', 'status', 'is_modified', 'source')
    list_filter = ('status', 'source', 'is_modified')
    search_fields = ('geography_node__code', 'kpi__code')
    raw_id_fields = ('geography_node', 'kpi', 'target_period', 'plan', 'channel', 'sku_group')


@admin.register(AllocationRecipe)
class AllocationRecipeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kpi', 'channel', 'version', 'is_current', 'is_active')
    list_filter = ('is_current', 'is_active')
    search_fields = ('code', 'name')


@admin.register(RevisionPolicy)
class RevisionPolicyAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'target_period', 'channel', 'entity_type',
                    'auto_approve_within_pct', 'hard_ceiling_pct', 'version', 'is_current', 'is_active')
    list_filter = ('is_current', 'is_active', 'requires_reason')
    search_fields = ('code', 'name')
    raw_id_fields = ('target_period', 'channel', 'entity_type')


@admin.register(TargetRevision)
class TargetRevisionAdmin(admin.ModelAdmin):
    list_display = ('id', 'allocation', 'old_value', 'new_value', 'delta_pct', 'band', 'status',
                    'source', 'requested_by', 'approved_by', 'created_at')
    list_filter = ('band', 'status', 'source')
    search_fields = ('allocation__geography_node__code',)
    raw_id_fields = ('allocation', 'requested_by', 'approved_by')
