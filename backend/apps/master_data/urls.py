from rest_framework.routers import DefaultRouter

from .views import SKUGroupViewSet, SKUViewSet, UOMConversionViewSet

router = DefaultRouter()
router.register('skus', SKUViewSet, basename='sku')
router.register('sku-groups', SKUGroupViewSet, basename='sku-group')
router.register('uom-conversions', UOMConversionViewSet, basename='uom-conversion')

urlpatterns = router.urls
