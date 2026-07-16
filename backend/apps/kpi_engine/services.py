"""KPIService — all business logic + DB writes for the KPI engine.

The only layer that writes KPIDefinition / Transaction rows. Views and the Celery
import task call into here; the calculator (engine) is read-only and called from here.
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Channel, GeographyNode, Node, NodeType
from apps.master_data.models import SKU, SKUGroup
from apps.master_data.services import MasterDataService

from . import periods
from .calculator import KPICalculator
from .expressions import ExpressionError, extract_names
from .models import (
    ExternalMetric,
    ExternalMetricValue,
    IntegrationBatch,
    KPIDefinition,
    Transaction,
)

_TXN_DECIMAL_FIELDS = ('gross_amount', 'discount_amount', 'tax_amount', 'net_amount', 'quantity')
_TXN_TYPES = {Transaction.SALE, Transaction.RETURN, Transaction.CREDIT_NOTE}
_TXN_LEVELS = {Transaction.PRIMARY, Transaction.SECONDARY, Transaction.TERTIARY}


def _to_decimal(value, field):
    raw = str(value).strip()
    if raw == '':
        return Decimal('0')
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        raise BusinessError(f'Invalid {field} value: "{value}"')


def _parse_date(value, field='transaction_date'):
    raw = str(value).strip()
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        raise BusinessError(f'Invalid {field} (expected YYYY-MM-DD): "{value}"')


class KPIService:

    # ── KPIDefinition CRUD (versioned) ──────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def create_kpi(data: dict, actor=None) -> KPIDefinition:
        data.setdefault('effective_from', date.today())
        code = data.get('code')
        if code and KPIDefinition.objects.filter(code=code, is_current=True).exists():
            raise BusinessError(f'A KPI with code "{code}" already exists.')
        errors = KPIService.validate_kpi_config(data)
        if errors:
            raise BusinessError(' '.join(errors))
        kpi = KPIDefinition.objects.create(**data)
        AuditService.log(
            'create', 'kpi_engine.KPIDefinition', kpi.id, actor,
            {'code': kpi.code, 'name': kpi.name, 'kpi_type': kpi.kpi_type, 'version': kpi.version},
        )
        return kpi

    @staticmethod
    @transaction.atomic
    def update_kpi(instance: KPIDefinition, data: dict, actor=None) -> KPIDefinition:
        """PUT semantics: retire the current version, create version+1 (config models
        are never edited in place — prior computations must stay reproducible)."""
        merged = {**_definition_to_dict(instance), **data, 'code': instance.code}
        errors = KPIService.validate_kpi_config(merged, exclude_code=instance.code)
        if errors:
            raise BusinessError(' '.join(errors))
        for attr, val in data.items():
            setattr(instance, attr, val)
        instance.create_new_version()
        AuditService.log(
            'update', 'kpi_engine.KPIDefinition', instance.id, actor,
            {'code': instance.code, 'new_version': instance.version},
        )
        return instance

    @staticmethod
    @transaction.atomic
    def deactivate_kpi(instance: KPIDefinition, actor=None) -> None:
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'kpi_engine.KPIDefinition', instance.id, actor, {'is_active': False})

    # ── config validation ───────────────────────────────────────────────────
    @staticmethod
    def validate_kpi_config(data: dict, exclude_code: str | None = None) -> list[str]:
        """Structural validation of a KPI config. Returns a list of human-readable
        errors (empty = valid). Shared by create/update and the /validate/ endpoint."""
        errors: list[str] = []
        kpi_type = data.get('kpi_type', KPIDefinition.VALUE)

        if kpi_type in (KPIDefinition.VALUE, KPIDefinition.COUNT, KPIDefinition.COUNT_DISTINCT):
            errors += _validate_measure(data.get('measure_config') or {}, kpi_type, 'Measure')

        elif kpi_type == KPIDefinition.RATIO:
            cfg = data.get('ratio_config') or {}
            if not cfg.get('numerator'):
                errors.append('Ratio KPI requires a numerator.')
            else:
                errors += _validate_measure(cfg['numerator'], None, 'Numerator')
            if not cfg.get('denominator'):
                errors.append('Ratio KPI requires a denominator.')
            else:
                errors += _validate_measure(cfg['denominator'], None, 'Denominator')

        elif kpi_type == KPIDefinition.GROWTH:
            cfg = data.get('growth_config') or {}
            basis = cfg.get('basis')
            if basis not in periods.BASIS_CHOICES:
                errors.append(f'Growth KPI needs a valid basis ({", ".join(periods.BASIS_CHOICES)}).')
            if basis == periods.CUSTOM_MONTH_OFFSET and not cfg.get('offset'):
                errors.append('Custom-offset growth KPI requires a non-zero "offset".')
            errors += _validate_measure(data.get('measure_config') or {}, None, 'Measure')

        elif kpi_type == KPIDefinition.BOOLEAN:
            cfg = data.get('boolean_config') or {}
            if cfg.get('operator') not in ('gte', 'gt', 'lte', 'lt', 'eq'):
                errors.append('Boolean KPI requires an operator (gte/gt/lte/lt/eq).')
            try:
                Decimal(str(cfg.get('threshold', 0)))
            except (InvalidOperation, ValueError):
                errors.append('Boolean KPI threshold must be numeric.')
            errors += _validate_measure(data.get('measure_config') or {}, None, 'Measure')

        elif kpi_type == KPIDefinition.EXTERNAL:
            cfg = data.get('external_config') or {}
            metric_code = cfg.get('metric_code')
            if not metric_code:
                errors.append('External KPI requires a metric_code.')
            elif not ExternalMetric.objects.filter(code=metric_code, is_active=True).exists():
                errors.append(f'External KPI references unknown metric "{metric_code}".')
            agg = cfg.get('aggregation')
            if agg and agg not in _EXTERNAL_AGGREGATIONS:
                errors.append(
                    f'External KPI aggregation must be one of {", ".join(sorted(_EXTERNAL_AGGREGATIONS))}.'
                )
            target_source = cfg.get('target_source', 'allocation')
            if target_source not in ('allocation', 'fixed'):
                errors.append('External KPI target_source must be "allocation" or "fixed".')
            if target_source == 'fixed':
                try:
                    if Decimal(str(cfg.get('fixed_target', 0))) <= 0:
                        errors.append('External KPI with a fixed target needs fixed_target > 0.')
                except (InvalidOperation, ValueError):
                    errors.append('External KPI fixed_target must be numeric.')

        elif kpi_type == KPIDefinition.COMPOSITE:
            cfg = data.get('composite_config') or {}
            expression = cfg.get('expression', '')
            if not expression.strip():
                errors.append('Composite KPI requires an expression.')
            else:
                try:
                    names = extract_names(expression)
                except ExpressionError as exc:
                    names = set()
                    errors.append(str(exc))
                own_code = data.get('code')
                for code in names:
                    if code == own_code:
                        errors.append('Composite KPI cannot reference itself.')
                    elif not KPIDefinition.objects.filter(
                        code=code, is_current=True, is_active=True,
                    ).exists():
                        errors.append(f'Composite references unknown KPI code "{code}".')

        # Shared scope filters
        for ch in data.get('channel_filter') or []:
            if not Channel.objects.filter(code=ch, is_active=True).exists():
                errors.append(f'Unknown channel code "{ch}".')
        for et in data.get('applicable_entity_types') or []:
            if not NodeType.objects.filter(code=et, is_current=True, is_active=True).exists():
                errors.append(f'Unknown entity type code "{et}".')
        sku_filter = data.get('sku_filter') or {}
        if sku_filter.get('type') == 'group':
            if not SKUGroup.objects.filter(code=sku_filter.get('group_code'), is_active=True).exists():
                errors.append(f'Unknown SKU group "{sku_filter.get("group_code")}".')
        elif sku_filter.get('type') == 'explicit':
            codes = [c for c in (sku_filter.get('sku_codes') or []) if c]
            if codes:
                known = set(SKU.objects.filter(
                    code__in=codes, is_active=True,
                ).values_list('code', flat=True))
                unknown = [c for c in codes if c not in known]
                if unknown:
                    listed = ', '.join(f'"{c}"' for c in unknown)
                    errors.append(f'Unknown SKU code(s): {listed}.')

        return errors

    # ── preview ─────────────────────────────────────────────────────────────
    @staticmethod
    def preview_kpi(kpi_data: dict, entity_id: int, period_start, period_end, as_of=None) -> dict:
        """Run an UNSAVED definition through the calculator so the wizard can preview a result
        before the KPI is saved. With ``as_of`` it returns the month-to-date value plus a
        run-rate projection to the full period (pace), the way FMCG dashboards forecast a month."""
        errors = KPIService.validate_kpi_config(kpi_data)
        if errors:
            raise BusinessError(' '.join(errors))
        kpi = KPIDefinition(**{k: v for k, v in kpi_data.items() if _is_model_field(k)})
        window_end = min(as_of, period_end) if as_of else period_end
        result = KPICalculator(kpi, period_start, window_end).compute_for_entity(entity_id)
        out = {
            'entity_id': entity_id, 'period_start': str(period_start), 'period_end': str(period_end),
            'kpi_type': kpi.kpi_type, 'unit': kpi.unit, 'result': str(result),
        }
        if as_of:
            total = periods.working_days_between(period_start, period_end)
            elapsed = periods.working_days_between(period_start, window_end)
            projected = periods.project_full_period(result, elapsed, total)
            quant = Decimal(10) ** -kpi.decimal_places
            out.update({
                'as_of': str(window_end),
                'mtd_value': str(result),
                'projected_full_period': str(projected.quantize(quant)),
                'pace_pct': str((Decimal(elapsed) / Decimal(total) * 100).quantize(Decimal('0.01')) if total else Decimal('0')),
                'working_days_elapsed': elapsed,
                'working_days_total': total,
            })
        return out

    # ── transaction bulk import (idempotent) ────────────────────────────────
    @staticmethod
    @transaction.atomic
    def bulk_import_transactions(csv_text: str, actor=None) -> dict:
        """Upsert transactions from CSV. Idempotent on (source, external_ref): re-importing
        the same file updates rows in place instead of duplicating them. All-or-nothing —
        if any row is invalid nothing is written."""
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise BusinessError('CSV is empty or has no header row.')
        header = {h.strip() for h in reader.fieldnames}
        for required in ('attributed_node_id', 'transaction_date'):
            if required not in header:
                raise BusinessError(f'CSV must include a "{required}" column.')

        parsed: list[dict] = []
        errors: list[dict] = []
        for i, raw in enumerate(reader, start=2):  # row 1 = header
            row = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v)
                   for k, v in raw.items()}
            try:
                parsed.append(_parse_txn_row(row))
            except BusinessError as exc:
                errors.append({'row': i, 'errors': [str(exc)]})

        if errors:
            return {'status': 'validation_failed', 'created': 0, 'updated': 0, 'errors': errors}

        created = updated = 0
        for fields in parsed:
            source = fields.get('source', '')
            ext_ref = fields.get('external_ref', '')
            if source and ext_ref:
                _, was_created = Transaction.objects.update_or_create(
                    source=source, external_ref=ext_ref, defaults={**fields, 'is_active': True},
                )
            else:
                Transaction.objects.create(**fields)
                was_created = True
            created += int(was_created)
            updated += int(not was_created)

        AuditService.log(
            'bulk_import', 'kpi_engine.Transaction', 0, actor,
            {'created': created, 'updated': updated, 'total': len(parsed)},
        )
        return {'status': 'success', 'created': created, 'updated': updated, 'errors': []}


class ExternalMetricService:
    """CRUD for the external-metric catalog (SFA / agency feed definitions)."""

    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> ExternalMetric:
        code = data.get('code')
        if code and ExternalMetric.objects.filter(code=code).exists():
            raise BusinessError(f'An external metric with code "{code}" already exists.')
        metric = ExternalMetric.objects.create(**data)
        AuditService.log(
            'create', 'kpi_engine.ExternalMetric', metric.id, actor,
            {'code': metric.code, 'name': metric.name, 'granularity': metric.granularity},
        )
        return metric

    @staticmethod
    @transaction.atomic
    def update(metric: ExternalMetric, data: dict, actor=None) -> ExternalMetric:
        # Grain/granularity are frozen once values exist — silently reinterpreting
        # historic facts would corrupt every KPI reading this metric.
        frozen = {'granularity', 'period_grain'}
        changing = {f for f in frozen if f in data and data[f] != getattr(metric, f)}
        if changing and metric.values.exists():
            raise BusinessError(
                f'Cannot change {", ".join(sorted(changing))} once values exist for this metric.'
            )
        for attr, val in data.items():
            setattr(metric, attr, val)
        metric.save()
        AuditService.log(
            'update', 'kpi_engine.ExternalMetric', metric.id, actor,
            {'code': metric.code, 'fields': sorted(data.keys())},
        )
        return metric

    @staticmethod
    @transaction.atomic
    def deactivate(metric: ExternalMetric, actor=None) -> None:
        in_use = KPIDefinition.objects.filter(
            is_current=True, is_active=True, kpi_type=KPIDefinition.EXTERNAL,
            external_config__metric_code=metric.code,
        ).values_list('code', flat=True)
        if in_use:
            raise BusinessError(
                f'Metric is referenced by KPI(s): {", ".join(sorted(in_use))}. Retire those first.'
            )
        metric.is_active = False
        metric.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'kpi_engine.ExternalMetric', metric.id, actor, {'is_active': False})


class IngestionService:
    """Machine push ingestion (JSON) with partial accept. Every push writes one
    IntegrationBatch: valid rows land (idempotent upsert), invalid rows come back —
    and are stored — with per-row errors so the source can fix and re-push. A
    duplicate ``client_batch_ref`` replays the original batch result instead of
    re-ingesting."""

    @staticmethod
    def push_metric_values(source: str, rows: list[dict], client_batch_ref: str = '', actor=None) -> dict:
        replay = _find_batch_replay(IntegrationBatch.METRIC_VALUES, source, client_batch_ref)
        if replay is not None:
            return replay

        metrics = {m.code: m for m in ExternalMetric.objects.filter(is_active=True)}
        errors: list[dict] = []
        created = updated = 0
        for i, row in enumerate(rows):
            try:
                fields = _parse_metric_row(row, metrics, source)
                with transaction.atomic():  # savepoint — one bad row never poisons the batch
                    was_created = _upsert_metric_value(fields)
            except Exception as exc:  # noqa: BLE001 — every failure becomes a row error
                errors.append({
                    'index': i,
                    'external_ref': str(row.get('external_ref') or '') if isinstance(row, dict) else '',
                    'errors': [str(exc)],
                    'row': row if isinstance(row, dict) else {'raw': str(row)},
                })
                continue
            created += int(was_created)
            updated += int(not was_created)

        return _record_batch(
            IntegrationBatch.METRIC_VALUES, source, client_batch_ref,
            received=len(rows), created=created, updated=updated, errors=errors, actor=actor,
        )

    @staticmethod
    def push_transactions(source: str, rows: list[dict], client_batch_ref: str = '', actor=None) -> dict:
        """JSON transaction push (DMS/SFA). Same protocol as push_metric_values:
        partial accept, idempotent upsert on (source, external_ref) — which is why
        external_ref is REQUIRED here — one IntegrationBatch per push."""
        replay = _find_batch_replay(IntegrationBatch.TRANSACTIONS, source, client_batch_ref)
        if replay is not None:
            return replay

        live_node_ids = set(GeographyNode.objects.filter(is_active=True).values_list('id', flat=True))
        errors: list[dict] = []
        created = updated = 0
        for i, row in enumerate(rows):
            try:
                fields = _parse_txn_push_row(row, source, live_node_ids)
                with transaction.atomic():  # savepoint — one bad row never poisons the batch
                    _, was_created = Transaction.objects.update_or_create(
                        source=fields['source'], external_ref=fields['external_ref'],
                        defaults={**fields, 'is_active': True},
                    )
            except Exception as exc:  # noqa: BLE001 — every failure becomes a row error
                errors.append({
                    'index': i,
                    'external_ref': str(row.get('external_ref') or '') if isinstance(row, dict) else '',
                    'errors': [str(exc)],
                    'row': row if isinstance(row, dict) else {'raw': str(row)},
                })
                continue
            created += int(was_created)
            updated += int(not was_created)

        return _record_batch(
            IntegrationBatch.TRANSACTIONS, source, client_batch_ref,
            received=len(rows), created=created, updated=updated, errors=errors, actor=actor,
        )

    @staticmethod
    @transaction.atomic
    def bulk_import_metric_values(csv_text: str, actor=None) -> dict:
        """CSV analogue for admin uploads via BulkJob. All-or-nothing, mirroring the
        transaction import: if any row is invalid nothing is written."""
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise BusinessError('CSV is empty or has no header row.')
        header = {h.strip() for h in reader.fieldnames}
        for required in ('metric_code', 'measured_on', 'value'):
            if required not in header:
                raise BusinessError(f'CSV must include a "{required}" column.')

        metrics = {m.code: m for m in ExternalMetric.objects.filter(is_active=True)}
        parsed: list[dict] = []
        errors: list[dict] = []
        for i, raw in enumerate(reader, start=2):  # row 1 = header
            row = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v)
                   for k, v in raw.items()}
            try:
                parsed.append(_parse_metric_row(row, metrics, default_source='manual_entry'))
            except BusinessError as exc:
                errors.append({'row': i, 'errors': [str(exc)]})

        if errors:
            return {'status': 'validation_failed', 'created': 0, 'updated': 0, 'errors': errors}

        created = updated = 0
        for fields in parsed:
            was_created = _upsert_metric_value(fields)
            created += int(was_created)
            updated += int(not was_created)

        AuditService.log(
            'bulk_import', 'kpi_engine.ExternalMetricValue', 0, actor,
            {'created': created, 'updated': updated, 'total': len(parsed)},
        )
        return {'status': 'success', 'created': created, 'updated': updated, 'errors': []}


def _find_batch_replay(kind: str, source: str, client_batch_ref: str) -> dict | None:
    if not client_batch_ref:
        return None
    batch = IntegrationBatch.objects.filter(
        batch_kind=kind, source=source, client_batch_ref=client_batch_ref,
    ).first()
    return _batch_summary(batch, replayed=True) if batch else None


def _record_batch(kind, source, client_batch_ref, *, received, created, updated, errors, actor) -> dict:
    accepted = created + updated
    if accepted == 0 and received > 0:
        batch_status = IntegrationBatch.REJECTED
    elif errors:
        batch_status = IntegrationBatch.PARTIAL
    else:
        batch_status = IntegrationBatch.ACCEPTED
    batch = IntegrationBatch.objects.create(
        batch_kind=kind, source=source, client_batch_ref=client_batch_ref,
        received_count=received, accepted_count=accepted, rejected_count=len(errors),
        row_errors=errors, status=batch_status,
        pushed_by=actor if getattr(actor, 'pk', None) else None,
    )
    AuditService.log(
        'bulk_import', 'kpi_engine.IntegrationBatch', batch.id, actor,
        {'kind': kind, 'source': source, 'received': received,
         'accepted': accepted, 'rejected': len(errors)},
    )
    summary = _batch_summary(batch)
    summary.update({'created': created, 'updated': updated})
    return summary


def _batch_summary(batch: IntegrationBatch, replayed: bool = False) -> dict:
    return {
        'batch_id': batch.id,
        'status': batch.status,
        'received': batch.received_count,
        'accepted': batch.accepted_count,
        'rejected': batch.rejected_count,
        'errors': [
            {k: e.get(k) for k in ('index', 'external_ref', 'errors')} for e in batch.row_errors
        ],
        'replayed': replayed,
    }


def _parse_metric_row(row: dict, metrics: dict, default_source: str) -> dict:
    if not isinstance(row, dict):
        raise BusinessError('Row must be an object.')
    metric = metrics.get(str(row.get('metric_code', '')).strip())
    if metric is None:
        raise BusinessError(f'Unknown metric_code "{row.get("metric_code")}".')

    measured_on = _parse_date(row.get('measured_on', ''), 'measured_on')
    if metric.period_grain == ExternalMetric.MONTHLY:
        measured_on = measured_on.replace(day=1)

    entity_id = row.get('entity_id')
    node_id = row.get('node_id')
    if metric.granularity == ExternalMetric.ENTITY:
        if not entity_id or node_id:
            raise BusinessError(f'Metric "{metric.code}" is person-grain: provide entity_id only.')
        if not Node.objects.filter(pk=entity_id, is_current=True, is_active=True).exists():
            raise BusinessError(f'Unknown entity_id {entity_id}.')
        node_id = None
    else:
        if not node_id or entity_id:
            raise BusinessError(f'Metric "{metric.code}" is territory-grain: provide node_id only.')
        if not GeographyNode.objects.filter(pk=node_id, is_active=True).exists():
            raise BusinessError(f'Unknown node_id {node_id}.')
        entity_id = None

    return {
        'metric': metric,
        'entity_id': entity_id,
        'node_id': node_id,
        'measured_on': measured_on,
        'value': _to_decimal(row.get('value', ''), 'value'),
        'source': str(row.get('source') or default_source or '').strip(),
        'external_ref': str(row.get('external_ref') or '').strip(),
    }


# Sources a machine push may claim (matches Transaction.source vocabulary).
_PUSH_SOURCES = {'api_push', 'dms_sync', 'sfa_sync'}


def _parse_txn_push_row(row: dict, default_source: str, live_node_ids: set) -> dict:
    """JSON analogue of _parse_txn_row: string-coerce, then share its validation.
    Push rows additionally require external_ref (idempotency key) and a live
    geography node."""
    if not isinstance(row, dict):
        raise BusinessError('Row must be an object.')
    fields = _parse_txn_row({k: ('' if v is None else str(v)) for k, v in row.items()})
    fields['source'] = fields['source'] or default_source
    if fields['source'] not in _PUSH_SOURCES:
        raise BusinessError(
            f'source must be one of {", ".join(sorted(_PUSH_SOURCES))}: "{fields["source"]}"'
        )
    if not fields['external_ref']:
        raise BusinessError('external_ref is required on pushed transactions (idempotency key).')
    if fields['attributed_node_id'] not in live_node_ids:
        raise BusinessError(f'Unknown attributed_node_id {fields["attributed_node_id"]}.')
    return fields


def _upsert_metric_value(fields: dict) -> bool:
    """Upsert one fact row; returns was_created. Keyed on (source, external_ref) when
    the source supplies a ref, else on the natural key."""
    if fields['source'] and fields['external_ref']:
        _, was_created = ExternalMetricValue.objects.update_or_create(
            source=fields['source'], external_ref=fields['external_ref'],
            defaults={**fields, 'is_active': True},
        )
        return was_created
    key = {'metric': fields['metric'], 'measured_on': fields['measured_on']}
    if fields['entity_id']:
        key['entity_id'] = fields['entity_id']
    else:
        key['node_id'] = fields['node_id']
    _, was_created = ExternalMetricValue.objects.update_or_create(
        **key, defaults={**fields, 'is_active': True},
    )
    return was_created


# ── module helpers ──────────────────────────────────────────────────────────
# Fields a KPI may aggregate. Deliberately excludes discount_amount / tax_amount — they remain
# on Transaction (used by reports/import) but are not offered as KPI measures.
_MEASURE_FIELDS = {
    'net_amount', 'gross_amount', 'quantity', 'base_quantity',
    'outlet_code', 'bill_ref', 'sku_code',
}
_AGGREGATIONS = {'sum', 'count', 'count_distinct', 'weighted_distinct'}
# Aggregations an external-metric KPI may apply over its fact rows.
_EXTERNAL_AGGREGATIONS = {ExternalMetric.SUM, ExternalMetric.AVG, ExternalMetric.LATEST, ExternalMetric.MAX}


def _validate_measure(cfg: dict, kpi_type, label: str) -> list[str]:
    errors = []
    agg = cfg.get('aggregation')
    if agg not in _AGGREGATIONS:
        errors.append(f'{label}: aggregation must be one of {", ".join(sorted(_AGGREGATIONS))}.')
    if agg in ('sum', 'count_distinct') and cfg.get('measure_field') not in _MEASURE_FIELDS:
        errors.append(f'{label}: a valid measure_field is required for {agg}.')
    if agg == 'weighted_distinct':
        if cfg.get('group_field') not in _MEASURE_FIELDS:
            errors.append(f'{label}: weighted_distinct needs a group_field (e.g. outlet_code).')
        if cfg.get('weight_field') not in _MEASURE_FIELDS:
            errors.append(f'{label}: weighted_distinct needs a weight_field (e.g. net_amount).')
    if kpi_type == KPIDefinition.VALUE and agg != 'sum':
        errors.append(f'{label}: a value KPI must use the "sum" aggregation.')
    if kpi_type == KPIDefinition.COUNT_DISTINCT and agg not in ('count_distinct', 'weighted_distinct'):
        errors.append(f'{label}: a count-distinct KPI must use "count_distinct" or "weighted_distinct".')
    having = cfg.get('having')
    if having:
        if agg != 'count_distinct':
            errors.append(f'{label}: a "having" threshold only applies to count_distinct.')
        if having.get('operator') not in ('gte', 'gt', 'lte', 'lt', 'eq'):
            errors.append(f'{label}: having.operator must be gte/gt/lte/lt/eq.')
        if having.get('field') not in _MEASURE_FIELDS:
            errors.append(f'{label}: having.field must be a valid measure field.')
    return errors


def _parse_txn_row(row: dict) -> dict:
    node_raw = (row.get('attributed_node_id') or '').strip()
    if not node_raw.isdigit():
        raise BusinessError(f'attributed_node_id must be an integer: "{node_raw}"')
    txn_type = (row.get('transaction_type') or Transaction.SALE).strip() or Transaction.SALE
    if txn_type not in _TXN_TYPES:
        raise BusinessError(f'Invalid transaction_type: "{txn_type}"')
    level = (row.get('transaction_level') or Transaction.SECONDARY).strip() or Transaction.SECONDARY
    if level not in _TXN_LEVELS:
        raise BusinessError(f'Invalid transaction_level: "{level}"')

    fields = {
        'attributed_node_id': int(node_raw),
        'transaction_date': _parse_date(row.get('transaction_date', '')),
        'transaction_type': txn_type,
        'transaction_level': level,
        'channel_code': (row.get('channel_code') or '').strip(),
        'sku_code': (row.get('sku_code') or '').strip(),
        'outlet_code': (row.get('outlet_code') or '').strip(),
        'bill_ref': (row.get('bill_ref') or '').strip(),
        'uom': (row.get('uom') or '').strip(),
        'source': (row.get('source') or '').strip(),
        'external_ref': (row.get('external_ref') or '').strip(),
    }
    for field in _TXN_DECIMAL_FIELDS:
        fields[field] = _to_decimal(row.get(field, ''), field)
    posted = (row.get('posted_date') or '').strip()
    fields['posted_date'] = _parse_date(posted, 'posted_date') if posted else None
    fields['base_quantity'] = MasterDataService.convert_to_base(
        fields['sku_code'], fields['uom'], fields['quantity'],
    )
    return fields


def _is_model_field(name: str) -> bool:
    return name in {f.name for f in KPIDefinition._meta.get_fields()}


def _definition_to_dict(instance: KPIDefinition) -> dict:
    return {
        'name': instance.name, 'code': instance.code, 'description': instance.description,
        'category': instance.category, 'unit': instance.unit,
        'decimal_places': instance.decimal_places, 'kpi_type': instance.kpi_type,
        'measure_config': instance.measure_config, 'ratio_config': instance.ratio_config,
        'growth_config': instance.growth_config, 'composite_config': instance.composite_config,
        'boolean_config': instance.boolean_config, 'external_config': instance.external_config,
        'applicable_entity_types': instance.applicable_entity_types,
        'channel_filter': instance.channel_filter, 'sku_filter': instance.sku_filter,
    }
