from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import SKU, SKUGroup, UOMConversion


class SKUSerializer(serializers.ModelSerializer):
    class Meta:
        model = SKU
        fields = [
            'id', 'code', 'name', 'brand', 'category', 'sub_category',
            'mrp', 'is_focus', 'is_npi', 'attributes',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def _actor(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def create(self, validated_data):
        from .services import MasterDataService
        return MasterDataService.create_sku(validated_data, actor=self._actor())

    def update(self, instance, validated_data):
        from .services import MasterDataService
        return MasterDataService.update_sku(instance, validated_data, actor=self._actor())


class SKUGroupSerializer(serializers.ModelSerializer):
    skus = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=SKU.objects.filter(is_active=True),
    )
    resolved_sku_count = serializers.SerializerMethodField()

    class Meta:
        model = SKUGroup
        fields = [
            'id', 'name', 'code', 'filter_type', 'filter_rules', 'skus',
            'resolved_sku_count', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    # Allowed keys in filter_rules: the fixed rule columns plus the nested attributes map.
    _ALLOWED_RULE_KEYS = frozenset(SKUGroup._RULE_FIELDS) | {'attributes'}

    @extend_schema_field(serializers.IntegerField())
    def get_resolved_sku_count(self, obj):
        # Explicit groups have their SKUs prefetched in the ViewSet queryset — count in
        # Python to avoid a per-row query. Rule groups still need a COUNT.
        if obj.filter_type == SKUGroup.FILTER_EXPLICIT:
            return sum(1 for s in obj.skus.all() if s.is_active)
        return obj.get_skus().count()

    def validate_filter_rules(self, value):
        unknown = set(value or {}) - self._ALLOWED_RULE_KEYS
        if unknown:
            allowed = ', '.join(sorted(self._ALLOWED_RULE_KEYS))
            raise serializers.ValidationError(
                f'Unknown rule field(s): {", ".join(sorted(unknown))}. Allowed: {allowed}.',
            )
        return value

    def _actor(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def create(self, validated_data):
        from .services import MasterDataService
        return MasterDataService.create_sku_group(validated_data, actor=self._actor())

    def update(self, instance, validated_data):
        from .services import MasterDataService
        return MasterDataService.update_sku_group(instance, validated_data, actor=self._actor())


class SKUBulkImportSerializer(serializers.Serializer):
    data = serializers.CharField(
        required=False, allow_blank=True,
        help_text='Raw CSV text (with a header row). Omit when uploading a file.',
    )
    file = serializers.FileField(
        required=False,
        help_text='CSV file. Takes precedence over the data field.',
    )
    run_async = serializers.BooleanField(
        required=False, default=False,
        help_text='Force background processing. Imports larger than the async threshold '
                  'are processed in the background regardless.',
    )

    def validate(self, attrs):
        if not attrs.get('data') and not attrs.get('file'):
            raise serializers.ValidationError('Provide either CSV text in "data" or a "file".')
        return attrs


class SKUGroupPreviewSerializer(serializers.Serializer):
    """Input for the unsaved-group preview. Validates the same shape as a group write."""
    filter_type = serializers.ChoiceField(choices=SKUGroup.FILTER_TYPE_CHOICES)
    filter_rules = serializers.JSONField(required=False, default=dict)
    skus = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=SKU.objects.filter(is_active=True),
    )

    def validate_filter_rules(self, value):
        return SKUGroupSerializer().validate_filter_rules(value)


class UOMConversionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UOMConversion
        fields = [
            'id', 'sku_code', 'from_uom', 'to_uom', 'factor',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def _actor(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def create(self, validated_data):
        from .services import MasterDataService
        return MasterDataService.create_uom_conversion(validated_data, actor=self._actor())

    def update(self, instance, validated_data):
        from .services import MasterDataService
        return MasterDataService.update_uom_conversion(instance, validated_data, actor=self._actor())
