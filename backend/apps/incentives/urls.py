from rest_framework.routers import DefaultRouter

from .views import (
    ExceptionCategoryViewSet,
    PayoutCycleViewSet,
    PayoutExceptionViewSet,
    PayoutRunViewSet,
    PayoutViewSet,
    SchemeViewSet,
    VariablePayViewSet,
)

router = DefaultRouter()
router.register('schemes', SchemeViewSet, basename='incentive-scheme')
router.register('variable-pay', VariablePayViewSet, basename='variable-pay')
router.register('cycles', PayoutCycleViewSet, basename='payout-cycle')
router.register('payout-runs', PayoutRunViewSet, basename='payout-run')
router.register('payouts', PayoutViewSet, basename='payout')
router.register('exceptions', PayoutExceptionViewSet, basename='payout-exception')
router.register('exception-categories', ExceptionCategoryViewSet, basename='exception-category')

urlpatterns = router.urls
