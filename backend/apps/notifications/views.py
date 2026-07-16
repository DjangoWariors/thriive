from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.core.pagination import StandardPagination

from .models import Notification
from .serializers import NotificationPreferenceSerializer, NotificationSerializer
from .services import CHANNELS, NotificationPreferenceService, NotificationService


@extend_schema_view(
    list=extend_schema(tags=['Notifications'], summary="Current user's notifications",
                       parameters=[OpenApiParameter('unread', type=bool)]),
)
class NotificationViewSet(mixins.ListModelMixin, GenericViewSet):
    """Own notifications only. No required_permission — any authenticated user, scoped to self."""

    serializer_class = NotificationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get('unread') in ('1', 'true'):
            qs = qs.filter(is_read=False)
        return qs

    @extend_schema(tags=['Notifications'], operation_id='notifications_unread_count',
                   summary='Unread notification count')
    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        return Response({'count': NotificationService.unread_count(request.user)})

    @extend_schema(tags=['Notifications'], operation_id='notification_mark_read',
                   summary='Mark one notification read', request=None,
                   responses={200: NotificationSerializer})
    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        notif = get_object_or_404(Notification, pk=pk, user=request.user)
        return Response(NotificationSerializer(NotificationService.mark_read(notif)).data)

    @extend_schema(tags=['Notifications'], operation_id='notifications_mark_all_read',
                   summary='Mark all notifications read', request=None)
    @action(detail=False, methods=['post'], url_path='read-all')
    def mark_all_read(self, request):
        n = NotificationService.mark_all_read(request.user)
        return Response({'marked': n})


class NotificationPreferenceView(APIView):
    """Own notification preferences. No required_permission — any authenticated
    user, scoped to self."""

    permission_classes = [IsAuthenticated]

    def _payload(self, user):
        return {
            'prefs': NotificationPreferenceService.get(user),
            'available_categories': NotificationPreferenceService.available_categories(),
            'channels': CHANNELS,
        }

    @extend_schema(tags=['Notifications'], operation_id='notification_prefs_get',
                   summary='Get own notification preferences',
                   responses={200: NotificationPreferenceSerializer})
    def get(self, request):
        return Response(NotificationPreferenceSerializer(self._payload(request.user)).data)

    @extend_schema(tags=['Notifications'], operation_id='notification_prefs_update',
                   summary='Update own notification preferences',
                   request=NotificationPreferenceSerializer,
                   responses={200: NotificationPreferenceSerializer})
    def patch(self, request):
        ser = NotificationPreferenceSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        NotificationPreferenceService.set(request.user, ser.validated_data['prefs'])
        return Response(NotificationPreferenceSerializer(self._payload(request.user)).data)
