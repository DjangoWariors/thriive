from django.contrib import admin

from .models import (
    ExternalMetric, ExternalMetricValue, IntegrationBatch, KPIDefinition, KpiTemplate, Transaction,
)


@admin.register(KpiTemplate)
class KpiTemplateAdmin(admin.ModelAdmin):
    list_display = ('display_order', 'code', 'name', 'kpi_type', 'category', 'unit', 'is_active')
    list_filter = ('kpi_type', 'category', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('display_order', 'name')


@admin.register(KPIDefinition)
class KPIDefinitionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kpi_type', 'category', 'unit', 'version', 'is_current', 'is_active')
    list_filter = ('kpi_type', 'category', 'is_current', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('code', '-version')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'attributed_node_id', 'transaction_date', 'transaction_type', 'transaction_level',
        'channel_code', 'sku_code', 'net_amount', 'quantity', 'source',
    )
    list_filter = ('transaction_type', 'transaction_level', 'channel_code', 'source')
    search_fields = ('attributed_node_id', 'sku_code', 'outlet_code', 'bill_ref', 'external_ref')
    date_hierarchy = 'transaction_date'


@admin.register(ExternalMetric)
class ExternalMetricAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'unit', 'granularity', 'period_grain',
                    'default_aggregation', 'is_active')
    list_filter = ('granularity', 'period_grain', 'default_aggregation', 'is_active')
    search_fields = ('code', 'name')


@admin.register(ExternalMetricValue)
class ExternalMetricValueAdmin(admin.ModelAdmin):
    list_display = ('id', 'metric', 'entity', 'node_id', 'measured_on', 'value',
                    'source', 'external_ref')
    list_filter = ('source',)
    search_fields = ('external_ref', 'entity__code')
    raw_id_fields = ('metric', 'entity')
    date_hierarchy = 'measured_on'


@admin.register(IntegrationBatch)
class IntegrationBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch_kind', 'source', 'client_batch_ref', 'status',
                    'received_count', 'accepted_count', 'rejected_count', 'created_at')
    list_filter = ('batch_kind', 'source', 'status')
    search_fields = ('client_batch_ref',)
    raw_id_fields = ('pushed_by',)
    date_hierarchy = 'created_at'
