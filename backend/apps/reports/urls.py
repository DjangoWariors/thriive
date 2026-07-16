from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DatasetView,
    DeliveryTargetViewSet,
    GenerateReportView,
    ReportDefinitionListView,
    ReportDownloadView,
    ReportExecutionViewSet,
    ReportScheduleViewSet,
)

router = DefaultRouter()
router.register('executions', ReportExecutionViewSet, basename='report-execution')
router.register('schedules', ReportScheduleViewSet, basename='report-schedule')
router.register('delivery-targets', DeliveryTargetViewSet, basename='delivery-target')

urlpatterns = [
    path('definitions/', ReportDefinitionListView.as_view(), name='report-definitions'),
    path('generate/', GenerateReportView.as_view(), name='report-generate'),
    path('executions/<int:pk>/download/', ReportDownloadView.as_view(), name='report-download'),
    path('datasets/<str:code>/', DatasetView.as_view(), name='report-dataset'),
    *router.urls,
]
