from rest_framework.routers import DefaultRouter

from .views import BulkJobViewSet

app_name = 'jobs'

router = DefaultRouter()
router.register(r'', BulkJobViewSet, basename='bulk-job')

urlpatterns = router.urls
