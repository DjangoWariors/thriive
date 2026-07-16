from drf_spectacular.extensions import OpenApiAuthenticationExtension


class JWTScheme(OpenApiAuthenticationExtension):
    """Registers BearerAuth JWT security scheme in the OpenAPI spec."""

    target_class = 'rest_framework_simplejwt.authentication.JWTAuthentication'
    name = 'BearerAuth'
    match_subclasses = False
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
        }


def filter_admin_urls(endpoints, **kwargs):
    return [
        (path, path_regex, method, callback)
        for path, path_regex, method, callback in endpoints
        if not path.startswith('/admin/')
    ]
