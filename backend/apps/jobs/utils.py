import csv
import io
import json


BULK_ASYNC_THRESHOLD = 500


def count_rows(raw, fmt: str) -> int:
    """
    Best-effort row count for deciding sync vs async. Never raises — a parse
    failure returns 0 so the request takes the synchronous path and the service
    surfaces the real error.
    """
    try:
        if fmt == 'csv':
            reader = csv.reader(io.StringIO(raw))
            total = sum(1 for _ in reader)
            return max(total - 1, 0)  # drop the header row
        data = json.loads(raw) if isinstance(raw, str) else raw
        return len(data) if isinstance(data, list) else 0
    except (ValueError, TypeError):
        return 0
