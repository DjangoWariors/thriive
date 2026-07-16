from rest_framework import serializers

from apps.admin_console.models import FeatureFlag, SystemSetting


class SystemSettingSerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField()
    raw_value = serializers.JSONField(write_only=True, source='value')

    class Meta:
        model = SystemSetting
        fields = ['id', 'key', 'category', 'value', 'raw_value', 'value_type',
                  'description', 'is_sensitive']
        read_only_fields = ['id']

    def get_value(self, obj):
        request = self.context.get('request')
        is_super = bool(request and request.user.is_superuser)
        if obj.is_sensitive and not is_super:
            return '••••••'
        return obj.value


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ['id', 'code', 'description', 'is_enabled', 'scope', 'scope_value']
        read_only_fields = ['id']


class SettingUpdateSerializer(serializers.Serializer):
    value = serializers.JSONField()
