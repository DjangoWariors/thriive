from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def _humanize(field: str) -> str:
    return field.replace('_', ' ').strip().capitalize()


def _flatten_detail(data) -> str:
    """Turn a DRF error payload into a single human-readable sentence.

    Handles plain strings, ``{'detail': ...}``, single-item lists, and
    field-error dicts like ``{'employee_id': ['... already exists.']}`` (which
    would otherwise stringify into an unreadable blob).
    """
    if isinstance(data, dict):
        if 'detail' in data:
            return _flatten_detail(data['detail'])
        parts = []
        for field, errors in data.items():
            message = _flatten_detail(errors)
            if not message:
                continue
            if field in ('non_field_errors', 'detail'):
                parts.append(message)
            else:
                parts.append(f'{_humanize(field)}: {message}')
        return ' '.join(parts) if parts else str(data)
    if isinstance(data, list):
        return ' '.join(_flatten_detail(item) for item in data if item != '')
    return str(data)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, BusinessError):
        return Response(
            {'error': True, 'status_code': 422, 'detail': exc.message,
             **({'code': exc.code} if exc.code else {})},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if response is not None:
        response.data = {
            'error': True,
            'status_code': response.status_code,
            'detail': _flatten_detail(response.data),
        }

    return response


class BusinessError(Exception):
    def __init__(self, message, code=None):
        self.message = message
        self.code = code
        super().__init__(message)
