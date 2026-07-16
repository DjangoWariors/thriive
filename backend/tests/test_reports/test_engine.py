"""Renderers + generator + scope — mostly pure, no HTTP."""
import csv
import io

import pytest

from apps.reports.renderers import csv_stream, pdf, xlsx
from apps.reports.renderers.base import Column, ReportResult
from apps.reports.scope import ReportScope

pytestmark = pytest.mark.django_db


def _sample():
    return ReportResult(
        title='Sample',
        columns=[Column('name', 'Name'), Column('amount', 'Amount', 'decimal')],
        rows=[{'name': 'A', 'amount': '100.00'}, {'name': 'B', 'amount': '250.50'}],
        summary={'amount': '350.50'},
        meta={'period': 'Jun 2026'},
    )


class TestRenderers:
    def test_csv_has_header_rows_and_total(self):
        out = csv_stream.render(_sample()).decode()
        reader = list(csv.reader(io.StringIO(out)))
        assert reader[0] == ['Name', 'Amount']
        assert reader[1] == ['A', '100.00']
        assert reader[-1][0] == 'TOTAL'
        assert reader[-1][1] == '350.50'

    def test_xlsx_renders_bytes(self):
        out = xlsx.render(_sample())
        assert out[:2] == b'PK'  # xlsx is a zip
        assert len(out) > 0

    def test_pdf_renders_bytes(self):
        out = pdf.render(_sample())
        assert out[:4] == b'%PDF'


class TestScope:
    def test_global_scope_passes_queryset_through(self, org):
        from apps.hierarchy.models import Node
        scope = ReportScope(is_global=True, home_path=None, home_entity_id=None)
        assert scope.filter_entities(Node.objects.all()).count() == 4

    def test_subtree_scope_limits_to_descendants(self, org):
        from apps.hierarchy.models import Node
        scope = ReportScope(is_global=False, home_path=org['asm'].path,
                            home_entity_id=org['asm'].pk)
        names = set(scope.filter_entities(Node.objects.all()).values_list('name', flat=True))
        assert names == {'Area Mgr', 'Deepa', 'Rahul'}  # ASM + its two ASEs, not NSM

    def test_unplaced_no_subtree_sees_nothing(self, org):
        from apps.hierarchy.models import Node
        scope = ReportScope(is_global=False, home_path=None, home_entity_id=None)
        assert scope.filter_entities(Node.objects.all()).count() == 0


class TestRosterGenerator:
    def test_roster_rows_scoped(self, org):
        from apps.reports.generators.master import NodeRosterGenerator
        scope = ReportScope(is_global=True, home_path=None, home_entity_id=None)
        result = NodeRosterGenerator().run({}, scope, None)
        assert result.row_count == 4
        assert {r['name'] for r in result.rows} == {'Nat Head', 'Area Mgr', 'Deepa', 'Rahul'}

    def test_roster_entity_type_filter(self, org):
        from apps.reports.generators.master import NodeRosterGenerator
        scope = ReportScope(is_global=True, home_path=None, home_entity_id=None)
        result = NodeRosterGenerator().run({'entity_type': 'ASE'}, scope, None)
        assert result.row_count == 2
