from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'code', 'category', 'title', 'body', 'link', 'is_read', 'read_at',
                  'created_at']


class NotificationPreferenceSerializer(serializers.Serializer):
    prefs = serializers.JSONField()
    available_categories = serializers.ListField(child=serializers.CharField(), read_only=True)
    channels = serializers.ListField(child=serializers.CharField(), read_only=True)
