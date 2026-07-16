from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import BulkJob
from .serializers import BulkJobSerializer

_JOB_LIST_PARAMS = [
    OpenApiParameter('job_type', str, description='Filter by job type (e.g. entity_import).'),
    OpenApiParameter('status', str, description='Filter by status (queued/running/completed/failed/partial).'),
]


@extend_schema_view(
    list=extend_schema(tags=['Jobs'], summary='List my bulk jobs', parameters=_JOB_LIST_PARAMS),
    retrieve=extend_schema(tags=['Jobs'], summary='Retrieve a bulk job (poll for status)'),
)
class BulkJobViewSet(ReadOnlyModelViewSet):
    """
    Read-only status feed for bulk operations. A user sees only the jobs they
    started; superusers see all.
    """

    serializer_class = BulkJobSerializer
    required_permission = None

    def get_queryset(self):
        qs = BulkJob.objects.all().order_by('-created_at')
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(created_by=user)

        params = self.request.query_params
        if job_type := params.get('job_type'):
            qs = qs.filter(job_type=job_type)
        if status_val := params.get('status'):
            qs = qs.filter(status=status_val)
        return qs
