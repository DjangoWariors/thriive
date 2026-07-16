from rest_framework.routers import DefaultRouter

from .views import GeographyNodeViewSet, GeographyTypeViewSet

router = DefaultRouter()
router.register('types', GeographyTypeViewSet, basename='geography-type')
router.register('nodes', GeographyNodeViewSet, basename='geography-node')

urlpatterns = router.urls
