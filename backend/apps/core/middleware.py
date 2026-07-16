import time
import uuid

import logging

logger = logging.getLogger(__name__)

SLOW_REQUEST_THRESHOLD_SECONDS = 2.0


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        request.client_ip = self._get_client_ip(request)

        start = time.monotonic()
        response = self.get_response(request)
        duration = time.monotonic() - start

        if duration > SLOW_REQUEST_THRESHOLD_SECONDS:
            logger.warning(
                'Slow request: %s %s took %.2fs (request_id=%s)',
                request.method, request.path, duration, request.request_id,
            )

        response['X-Request-ID'] = request.request_id
        return response

    def _get_client_ip(self, request):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')
