"""ReportResult → branded A4 PDF bytes (reportlab).

Generalizes the maroon-letterhead table builder first written in
the platform PDF style guide so all platform PDFs share one look.
"""
import io

from .base import cell_text, ReportResult

_PRIMARY = '#8B1A1A'
_TINT = '#FDF2F2'


def render(result: ReportResult) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    wide = len(result.columns) > 6
    pagesize = landscape(A4) if wide else A4

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(f'<b>{result.title}</b>', styles['Title'])]
    if result.confidential:
        story.append(Paragraph('<font color="%s"><b>CONFIDENTIAL</b></font>' % _PRIMARY,
                               styles['Normal']))
    story.append(Spacer(1, 6))
    for k, v in (result.meta or {}).items():
        story.append(Paragraph(f'<b>{k.replace("_", " ").title()}:</b> {v}', styles['Normal']))
    story.append(Spacer(1, 10))

    data = [[c.label for c in result.columns]]
    for row in result.rows:
        data.append([cell_text(row.get(c.key), c.type) for c in result.columns])
    if result.summary:
        data.append([_summary_cell(result, c, i) for i, c in enumerate(result.columns)])

    table = Table(data, repeatRows=1, hAlign='LEFT')
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(_PRIMARY)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(_TINT)]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    # Right-align numeric columns.
    for i, c in enumerate(result.columns):
        if c.type in ('decimal', 'integer', 'percent'):
            style.append(('ALIGN', (i, 0), (i, -1), 'RIGHT'))
    if result.summary:
        style.append(('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'))
    table.setStyle(TableStyle(style))
    story.append(table)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def _summary_cell(result, col, index):
    if result.summary.get(col.key) is not None:
        return cell_text(result.summary.get(col.key), col.type)
    return 'TOTAL' if index == 0 else ''


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColorRGB(0.5, 0.5, 0.5)
    canvas.drawRightString(doc.pagesize[0] - 14 * 2.83, 10 * 2.83,
                           f'Page {doc.page} · Thriive')
    canvas.restoreState()
