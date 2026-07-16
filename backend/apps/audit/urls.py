from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AccessLogViewSet,
    AuditLogViewSet,
    ChainVerifyView,
    ComputationLogViewSet,
    RecordHistoryView,
)

router = DefaultRouter()
router.register('logs', AuditLogViewSet, basename='audit-log')
router.register('computation-logs', ComputationLogViewSet, basename='computation-log')
router.register('access-logs', AccessLogViewSet, basename='access-log')

urlpatterns = [
    # Explicit paths first so they win over the router's /logs/{pk}/ detail route.
    path('logs/<str:entity_type>/<int:entity_id>/', RecordHistoryView.as_view(),
         name='audit-record-history'),
    path('verify/', ChainVerifyView.as_view(), name='audit-verify'),
    *router.urls,
]
