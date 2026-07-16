from django.contrib import admin

from .models import (
    ExceptionCategory, IncentiveScheme, MultiplierTier, Payout, PayoutCycle,
    PayoutException, PayoutLineItem, PayoutRun, SchemeGate, SchemeKPI, VariablePay,
)


class SchemeKPIInline(admin.TabularInline):
    model = SchemeKPI
    extra = 0
    raw_id_fields = ('kpi',)


class SchemeGateInline(admin.TabularInline):
    model = SchemeGate
    extra = 0
    raw_id_fields = ('kpi',)


@admin.register(IncentiveScheme)
class IncentiveSchemeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'target_entity_type', 'channel', 'payout_frequency',
                    'vp_basis_pct', 'gatekeeper_action', 'version', 'is_current', 'is_active')
    list_filter = ('payout_frequency', 'gatekeeper_action', 'is_current', 'is_active')
    search_fields = ('code', 'name')
    raw_id_fields = ('target_entity_type', 'channel')
    inlines = [SchemeKPIInline, SchemeGateInline]


class MultiplierTierInline(admin.TabularInline):
    model = MultiplierTier
    extra = 0


@admin.register(SchemeKPI)
class SchemeKPIAdmin(admin.ModelAdmin):
    list_display = ('id', 'scheme', 'kpi', 'incentive_category', 'weightage',
                    'min_qualifying_pct', 'multiplier_cap', 'display_order')
    list_filter = ('incentive_category',)
    search_fields = ('scheme__code', 'kpi__code')
    raw_id_fields = ('scheme', 'kpi')
    inlines = [MultiplierTierInline]


@admin.register(SchemeGate)
class SchemeGateAdmin(admin.ModelAdmin):
    list_display = ('id', 'scheme', 'kpi', 'operator', 'threshold_pct', 'display_order')
    search_fields = ('scheme__code', 'kpi__code')
    raw_id_fields = ('scheme', 'kpi')


@admin.register(VariablePay)
class VariablePayAdmin(admin.ModelAdmin):
    list_display = ('id', 'entity', 'target_period', 'amount', 'eligible_working_days', 'source')
    list_filter = ('source',)
    search_fields = ('entity__code', 'entity__name')
    raw_id_fields = ('entity', 'target_period')


@admin.register(PayoutCycle)
class PayoutCycleAdmin(admin.ModelAdmin):
    list_display = ('id', 'target_period', 'status', 'readiness_overridden', 'finalized_at',
                    'approved_at', 'disbursed_at', 'register_ref', 'total_payout')
    list_filter = ('status', 'readiness_overridden')
    raw_id_fields = ('target_period', 'finalized_by', 'submitted_by', 'approved_by', 'disbursed_by')


@admin.register(PayoutRun)
class PayoutRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'scheme', 'target_period', 'kind', 'status', 'entities_processed',
                    'error_count', 'total_payout', 'created_at')
    list_filter = ('kind', 'status')
    search_fields = ('scheme__code',)
    raw_id_fields = ('scheme', 'target_period', 'cycle', 'reference_run',
                     'triggered_by', 'submitted_by', 'approved_by')


class PayoutLineItemInline(admin.TabularInline):
    model = PayoutLineItem
    extra = 0
    raw_id_fields = ('scheme_kpi',)


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'entity', 'scheme', 'target_period', 'eligible_vp',
                    'total_multiplier', 'total_payout', 'gatekeeper_status', 'hold_status')
    list_filter = ('gatekeeper_status', 'hold_status', 'capped')
    search_fields = ('entity__code', 'entity__name')
    raw_id_fields = ('run', 'scheme', 'target_period', 'entity', 'exception')
    inlines = [PayoutLineItemInline]


@admin.register(PayoutLineItem)
class PayoutLineItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'payout', 'kpi_code', 'achievement_pct', 'applied_multiplier',
                    'weighted_multiplier', 'line_payout', 'treatment')
    list_filter = ('treatment',)
    search_fields = ('kpi_code',)
    raw_id_fields = ('payout', 'scheme_kpi')


@admin.register(PayoutException)
class PayoutExceptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'entity', 'target_period', 'scheme', 'category', 'sales_kpi_action',
                    'execution_kpi_action', 'gatekeeper_action', 'status')
    list_filter = ('status', 'sales_kpi_action', 'execution_kpi_action', 'gatekeeper_action')
    search_fields = ('entity__code', 'entity__name', 'category')
    raw_id_fields = ('entity', 'target_period', 'parent', 'scheme', 'category_ref',
                     'requested_by', 'approved_by')


@admin.register(ExceptionCategory)
class ExceptionCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'channel', 'requires_dates', 'workflow_definition_code',
                    'version', 'is_current', 'is_active')
    list_filter = ('requires_dates', 'is_current', 'is_active')
    search_fields = ('code', 'name')
    raw_id_fields = ('channel',)
