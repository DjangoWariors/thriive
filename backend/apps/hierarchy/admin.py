from django.contrib import admin

from .models import (
    Channel, GeographyNode, GeographyType, Node, NodeRelationship, NodeType, RelationshipType,
)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active')
    search_fields = ('code', 'name')


@admin.register(GeographyType)
class GeographyTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active')
    search_fields = ('code', 'name')


@admin.register(GeographyNode)
class GeographyNodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'level', 'geography_type', 'parent', 'depth', 'is_active')
    list_filter = ('geography_type', 'level', 'is_active')
    search_fields = ('code', 'name', 'path')
    raw_id_fields = ('geography_type', 'parent')


@admin.register(NodeType)
class NodeTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'level_order', 'is_loginable', 'incentive_eligible',
                    'is_root_type', 'is_leaf', 'version', 'is_current', 'is_active')
    list_filter = ('is_loginable', 'incentive_eligible', 'is_current', 'is_active')
    search_fields = ('code', 'name')
    raw_id_fields = ('default_role', 'channel')


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'entity_type', 'parent', 'channel', 'status',
                    'depth', 'version', 'is_current', 'is_active')
    list_filter = ('entity_type', 'channel', 'status', 'is_current', 'is_active')
    search_fields = ('code', 'name', 'path')
    raw_id_fields = ('entity_type', 'parent', 'channel')


@admin.register(RelationshipType)
class RelationshipTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'from_entity_type', 'to_entity_type', 'allows_multiple', 'is_active')
    search_fields = ('code', 'name')
    raw_id_fields = ('from_entity_type', 'to_entity_type')


@admin.register(NodeRelationship)
class NodeRelationshipAdmin(admin.ModelAdmin):
    list_display = ('id', 'relationship_type', 'from_entity', 'to_entity',
                    'effective_from', 'effective_to', 'is_active')
    list_filter = ('relationship_type', 'is_active')
    search_fields = ('from_entity__code', 'from_entity__name', 'to_entity__code', 'to_entity__name')
    raw_id_fields = ('relationship_type', 'from_entity', 'to_entity')
