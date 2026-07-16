from rest_framework.routers import DefaultRouter

from .views import NodeTypeViewSet

router = DefaultRouter()
router.register('', NodeTypeViewSet, basename='entity-type')

urlpatterns = router.urls
