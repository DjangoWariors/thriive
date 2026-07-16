"""ReportResult → CSV, streamed row-by-row so large registers never fully
materialize a string in memory."""
import csv
import io
from collections.abc import Iterator

from .base import cell_text, ReportResult


def iter_lines(result: ReportResult) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)

    def flush() -> str:
        line = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return line

    writer.writerow([c.label for c in result.columns])
    yield flush()

    for row in result.rows:
        writer.writerow([cell_text(row.get(c.key), c.type) for c in result.columns])
        yield flush()

    if result.summary:
        writer.writerow([
            cell_text(result.summary.get(c.key), c.type) if result.summary.get(c.key) is not None
            else ('TOTAL' if i == 0 else '')
            for i, c in enumerate(result.columns)
        ])
        yield flush()


def render(result: ReportResult) -> bytes:
    return ''.join(iter_lines(result)).encode('utf-8')
