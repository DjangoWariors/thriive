from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import NotificationPreferenceView, NotificationViewSet

router = DefaultRouter()
router.register('', NotificationViewSet, basename='notification')

urlpatterns = [
    # Must precede the router: its '' prefix would capture 'preferences' as a pk.
    path('preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),
    *router.urls,
]
