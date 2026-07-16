from rest_framework.routers import DefaultRouter

from .views import AchievementViewSet, AlertRuleViewSet, AlertViewSet

router = DefaultRouter()
router.register('alert-rules', AlertRuleViewSet, basename='alert-rule')
router.register('alerts', AlertViewSet, basename='alert')
router.register('', AchievementViewSet, basename='achievement')

urlpatterns = router.urls
