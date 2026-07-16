from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ApiKeyViewSet,
    ChangePasswordView,
    CurrentUserView,
    LogoutView,
    OTPRequestView,
    OTPVerifyView,
    PasswordLoginView,
    PermissionCatalogView,
    RoleViewSet,
    TokenRefreshView,
    UserViewSet,
)

app_name = 'accounts'

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')
router.register('roles', RoleViewSet, basename='role')
router.register('api-keys', ApiKeyViewSet, basename='api-key')

urlpatterns = [
    path('login/', PasswordLoginView.as_view(), name='login-password'),
    path('login/otp/request/', OTPRequestView.as_view(), name='otp-request'),
    path('login/otp/verify/', OTPVerifyView.as_view(), name='otp-verify'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', CurrentUserView.as_view(), name='me'),
    path('me/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('permission-catalog/', PermissionCatalogView.as_view(), name='permission-catalog'),
    path('', include(router.urls)),
]
