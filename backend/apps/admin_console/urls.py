from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    FeatureFlagViewSet,
    JobsMonitorViewSet,
    SchedulesHealthView,
    SystemHealthView,
    SystemSettingViewSet,
)

router = DefaultRouter()
router.register('settings', SystemSettingViewSet, basename='system-setting')
router.register('feature-flags', FeatureFlagViewSet, basename='feature-flag')
router.register('jobs', JobsMonitorViewSet, basename='admin-job')

urlpatterns = [
    path('schedules/', SchedulesHealthView.as_view(), name='admin-schedules'),
    path('system/health/', SystemHealthView.as_view(), name='admin-system-health'),
    *router.urls,
]
