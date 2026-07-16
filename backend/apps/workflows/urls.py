from rest_framework.routers import DefaultRouter

from .views import (
    ApprovalDelegationViewSet,
    WorkflowDefinitionViewSet,
    WorkflowInstanceViewSet,
)

router = DefaultRouter()
# Instance actions: /pending/, /pending/count/, /bulk-approve/, /bulk-reject/,
# /{id}/, /{id}/approve/, /{id}/reject/, /{id}/history/
router.register('definitions', WorkflowDefinitionViewSet, basename='workflow-definition')
router.register('delegations', ApprovalDelegationViewSet, basename='workflow-delegation')
router.register('', WorkflowInstanceViewSet, basename='workflow')

urlpatterns = router.urls
