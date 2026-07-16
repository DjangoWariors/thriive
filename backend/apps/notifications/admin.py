from django.contrib import admin

from .models import Notification, NotificationPreference, NotificationTemplate


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ('code', 'event', 'channel', 'category', 'is_active')
    list_filter = ('channel', 'category')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'category', 'title', 'is_read', 'created_at')
    list_filter = ('category', 'is_read')


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'is_active')
    search_fields = ('user__email',)
    raw_id_fields = ('user',)
