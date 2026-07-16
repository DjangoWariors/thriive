from rest_framework.routers import DefaultRouter

from .views import (
    AllocationRecipeViewSet,
    PlanRunViewSet,
    ReviewTaskViewSet,
    RevisionPolicyViewSet,
    TargetAllocationViewSet,
    TargetPeriodViewSet,
    TargetPlanViewSet,
    TargetRevisionViewSet,
)

router = DefaultRouter()
router.register('plans', TargetPlanViewSet, basename='target-plan')
router.register('runs', PlanRunViewSet, basename='target-plan-run')
router.register('review-tasks', ReviewTaskViewSet, basename='target-review-task')
router.register('recipes', AllocationRecipeViewSet, basename='allocation-recipe')
router.register('periods', TargetPeriodViewSet, basename='target-period')
router.register('allocations', TargetAllocationViewSet, basename='target-allocation')
router.register('revision-policies', RevisionPolicyViewSet, basename='revision-policy')
router.register('revisions', TargetRevisionViewSet, basename='target-revision')

urlpatterns = router.urls
