from rest_framework.routers import DefaultRouter, SimpleRouter

from .views import NodeRelationshipViewSet, NodeViewSet, RelationshipTypeViewSet


_rel_router = SimpleRouter()
_rel_router.register(r'relationship-types', RelationshipTypeViewSet, basename='relationship-type')
_rel_router.register(r'entity-relationships', NodeRelationshipViewSet, basename='entity-relationship')

_entity_router = DefaultRouter()
_entity_router.register(r'', NodeViewSet, basename='entity')

urlpatterns = _rel_router.urls + _entity_router.urls
