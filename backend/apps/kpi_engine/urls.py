from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ExternalMetricViewSet,
    IntegrationBatchViewSet,
    KPIDefinitionViewSet,
    KpiTemplateViewSet,
    MetricValuePushView,
    MetricValueViewSet,
    TransactionPushView,
    TransactionViewSet,
)

router = DefaultRouter()
router.register('definitions', KPIDefinitionViewSet, basename='kpi-definition')
router.register('templates', KpiTemplateViewSet, basename='kpi-template')
router.register('transactions', TransactionViewSet, basename='transaction')
router.register('external-metrics', ExternalMetricViewSet, basename='external-metric')
router.register('metric-values', MetricValueViewSet, basename='metric-value')
router.register('integration-batches', IntegrationBatchViewSet, basename='integration-batch')

urlpatterns = [
    # Before the router so 'push' is never swallowed by the detail routes.
    path('metric-values/push/', MetricValuePushView.as_view(), name='metric-values-push'),
    path('transactions/push/', TransactionPushView.as_view(), name='transactions-push'),
    *router.urls,
]
