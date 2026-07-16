from django.contrib import admin

from .models import Achievement, AchievementSnapshot, Alert, AlertRule, TerritoryAchievement


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('id', 'entity', 'kpi', 'target_period', 'channel', 'target_value',
                    'achieved_value', 'achievement_pct', 'is_provisional', 'computed_at')
    list_filter = ('is_provisional',)
    search_fields = ('entity__code', 'entity__name', 'kpi__code')
    raw_id_fields = ('entity', 'kpi', 'target_period', 'channel')


@admin.register(AchievementSnapshot)
class AchievementSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'achievement', 'snapshot_date', 'achieved_value',
                    'achievement_pct', 'projected_pct')
    raw_id_fields = ('achievement',)
    date_hierarchy = 'snapshot_date'


@admin.register(TerritoryAchievement)
class TerritoryAchievementAdmin(admin.ModelAdmin):
    list_display = ('id', 'node', 'kpi', 'target_period', 'channel', 'sku_group',
                    'target_value', 'achieved_value', 'achievement_pct', 'computed_at')
    search_fields = ('node__code', 'node__name', 'kpi__code')
    raw_id_fields = ('node', 'kpi', 'target_period', 'channel', 'sku_group')


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'metric', 'comparator', 'threshold', 'severity',
                    'is_enabled', 'version', 'is_current', 'is_active')
    list_filter = ('metric', 'severity', 'is_enabled', 'is_current', 'is_active')
    search_fields = ('code', 'name')
    raw_id_fields = ('kpi',)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'rule', 'entity', 'target_period', 'severity', 'status',
                    'metric_value', 'computed_at')
    list_filter = ('severity', 'status')
    search_fields = ('entity__code', 'entity__name', 'rule__code')
    raw_id_fields = ('rule', 'entity', 'target_period', 'kpi')
