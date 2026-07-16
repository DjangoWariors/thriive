"""The neutral tabular shape every generator produces and every renderer consumes.

A generator returns a ReportResult; renderers turn it into XLSX / PDF / CSV bytes.
No generator writes a file or knows about Excel styling — that is the renderers' job.
"""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Column:
    key: str
    label: str
    type: str = 'string'          # string | integer | decimal | percent | date
    width: int | None = None      # character width hint for XLSX autosizing


@dataclass
class ReportResult:
    title: str
    columns: list[Column]
    rows: list[dict]                          # each dict keyed by Column.key
    meta: dict = field(default_factory=dict)  # period, filters, generated_by/at, computation_refs
    summary: dict | None = None               # totals row keyed by Column.key
    confidential: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


# Maroon brand colour — the shared palette for all platform PDFs.
BRAND_PRIMARY = '8B1A1A'
BRAND_TINT = 'FDF2F2'


def cell_text(value, col_type: str) -> str:
    """Render a value as plain text for CSV/PDF (XLSX keeps native types)."""
    if value is None:
        return ''
    if col_type == 'percent':
        return f'{value}%'
    if col_type in ('decimal', 'integer') and isinstance(value, (Decimal, int, float)):
        return str(value)
    return str(value)
