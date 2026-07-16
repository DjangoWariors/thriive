import threading

# Thread-local storage so service-layer code can read the current request context
# (request_id, acting user) without needing it passed down every call stack.
_audit_context = threading.local()


def get_current_request():
    """Return the current Django request, or None if called outside a request."""
    return getattr(_audit_context, 'request', None)


class AuditMiddleware:
    """
    Attaches the current request to thread-local storage for the duration of each
    request/response cycle. Service-layer code calls get_current_request() when it
    needs the request context (e.g. IP, request_id) without explicit parameter passing.

    Explicit per-entity logging is done via AuditService.log() inside services.py.
    This middleware is intentionally lightweight — it does NOT auto-log every mutation
    (that would create duplicate entries alongside service-level logs).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _audit_context.request = request
        try:
            response = self.get_response(request)
        finally:
            _audit_context.request = None
        return response
