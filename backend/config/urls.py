from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    # Auth
    path('api/v1/auth/', include('apps.accounts.urls')),
    # Hierarchy
    path('api/v1/channels/',      include('apps.hierarchy.urls_channels')),
    path('api/v1/entity-types/',  include('apps.hierarchy.urls_entity_types')),
    path('api/v1/entities/',      include('apps.hierarchy.urls_entities')),
    path('api/v1/geography/',     include('apps.hierarchy.urls_geography')),
    # Assignments — effective-dated bridge between geography & organisation trees
    path('api/v1/assignments/',   include('apps.assignments.urls')),
    # Master data
    path('api/v1/master/',        include('apps.master_data.urls')),
    # KPI engine
    path('api/v1/kpis/',          include('apps.kpi_engine.urls')),
    # Targets & disaggregation
    path('api/v1/targets/',       include('apps.targets.urls')),
    # Achievements & dashboard
    path('api/v1/achievements/',  include('apps.achievements.urls')),
    # Incentives & payouts
    path('api/v1/incentives/',    include('apps.incentives.urls')),
    # Workflows & approvals
    path('api/v1/workflows/',     include('apps.workflows.urls')),
    # Audit, integrity & disclosure trail
    path('api/v1/audit/',         include('apps.audit.urls')),
    # Reports — async generation + download
    path('api/v1/reports/',       include('apps.reports.urls')),
    # System administration — settings, flags, ops monitoring
    path('api/v1/admin/',         include('apps.admin_console.urls')),
    # Bulk job status
    path('api/v1/jobs/',          include('apps.jobs.urls')),
    # Notifications
    path('api/v1/notifications/', include('apps.notifications.urls')),
]

from django.conf import settings  # noqa: E402
from django.conf.urls.static import static  # noqa: E402

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
