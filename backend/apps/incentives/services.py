"""Incentive business logic — the only layer that writes incentive models.

SchemeService     — versioned scheme config (scheme + KPIs + tiers as one unit).
VariablePayService — per entity × period pay base, single + bulk upsert.
ExceptionService  — maker-checker exception lifecycle + resolution map for compute.
PayoutService     — run lifecycle (compute → review → approve → paid), the ORM↔engine
                    bridge, breakdowns, and the dashboard integration payload.
"""
import csv
import io
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.audit.models import ComputationLog
from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.core.scoping import requester_can_reach_entity

from . import payout_engine as engine
from .models import (
    ExceptionCategory,
    IncentiveScheme,
    MultiplierTier,
    Payout,
    PayoutCycle,
    PayoutException,
    PayoutLineItem,
    PayoutRun,
    SchemeGate,
    SchemeKPI,
    VariablePay,
)

# Platform-default workflow when a category names none.
DEFAULT_EXCEPTION_WORKFLOW = 'payout_exception_standard'

_HUNDRED = Decimal('100')


def _tier_inputs(tiers) -> tuple[engine.TierInput, ...]:
    return tuple(
        engine.TierInput(
            min_pct=Decimal(str(t['min_achievement_pct'])) if isinstance(t, dict) else t.min_achievement_pct,
            max_pct=(
                (Decimal(str(t['max_achievement_pct'])) if t.get('max_achievement_pct') is not None else None)
                if isinstance(t, dict) else t.max_achievement_pct
            ),
            multiplier=Decimal(str(t['multiplier'])) if isinstance(t, dict) else t.multiplier,
        )
        for t in tiers
    )


class SchemeService:

    @staticmethod
    def validate_config(data: dict) -> list[str]:
        """Validate a full scheme payload (dict shape produced by SchemeWriteSerializer).
        Returns a list of error strings; empty = valid."""
        errors: list[str] = []

        entity_type = data.get('target_entity_type')
        if entity_type is not None and not entity_type.incentive_eligible:
            errors.append(
                f'Node type {entity_type.code} is not incentive-eligible.'
            )

        vp_basis = data.get('vp_basis_pct', Decimal('100'))
        if not (0 < vp_basis <= 100):
            errors.append('vp_basis_pct must be greater than 0 and at most 100.')
        overall_cap = data.get('overall_cap_pct')
        if overall_cap is not None and overall_cap <= 0:
            errors.append('overall_cap_pct must be greater than 0.')

        seen_gate_kpi_ids = set()
        for i, gate in enumerate(data.get('gates') or [], start=1):
            gate_kpi = gate.get('kpi')
            if gate_kpi is not None:
                if gate_kpi.pk in seen_gate_kpi_ids:
                    errors.append(f'Gate KPI {gate_kpi.code} appears more than once.')
                seen_gate_kpi_ids.add(gate_kpi.pk)
            if gate.get('operator', SchemeGate.GTE) not in (SchemeGate.GTE, SchemeGate.GT):
                errors.append(f'Gate #{i}: operator must be gte or gt.')
            threshold = gate.get('threshold_pct')
            if threshold is None or threshold <= 0:
                errors.append(f'Gate #{i}: threshold must be greater than 0.')

        kpis = data.get('kpis') or []
        if not kpis:
            errors.append('At least one KPI is required.')
        seen_kpi_ids = set()
        total_weight = Decimal('0')
        for i, row in enumerate(kpis, start=1):
            kpi = row.get('kpi')
            if kpi is not None:
                if kpi.pk in seen_kpi_ids:
                    errors.append(f'KPI {kpi.code} appears more than once.')
                seen_kpi_ids.add(kpi.pk)
            weight = row.get('weightage') or Decimal('0')
            if weight <= 0:
                errors.append(f'KPI #{i}: weightage must be greater than 0.')
            total_weight += weight
            mq = row.get('min_qualifying_pct')
            if mq is not None and mq < 0:
                errors.append(f'KPI #{i}: min_qualifying_pct cannot be negative.')
            cap = row.get('multiplier_cap')
            if cap is not None and cap <= 0:
                errors.append(f'KPI #{i}: multiplier_cap must be greater than 0.')
            tier_errors = engine.validate_tiers(_tier_inputs(row.get('tiers') or []))
            errors.extend(f'KPI #{i}: {e}' for e in tier_errors)
        if kpis and total_weight != Decimal('100.00'):
            errors.append(f'KPI weightages must sum to exactly 100.00 (got {total_weight}).')

        return errors

    @staticmethod
    def _save_children(scheme: IncentiveScheme, kpi_rows: list[dict],
                       gate_rows: list[dict] | None = None) -> None:
        SchemeGate.objects.bulk_create([
            SchemeGate(
                scheme=scheme,
                kpi=gate['kpi'],
                operator=gate.get('operator', SchemeGate.GTE),
                threshold_pct=gate['threshold_pct'],
                display_order=gate.get('display_order', order),
            )
            for order, gate in enumerate(gate_rows or [])
        ])
        for order, row in enumerate(kpi_rows):
            scheme_kpi = SchemeKPI.objects.create(
                scheme=scheme,
                kpi=row['kpi'],
                incentive_category=row.get('incentive_category', SchemeKPI.SALES),
                weightage=row['weightage'],
                min_qualifying_pct=row.get('min_qualifying_pct'),
                multiplier_cap=row.get('multiplier_cap'),
                display_order=row.get('display_order', order),
            )
            MultiplierTier.objects.bulk_create([
                MultiplierTier(
                    scheme_kpi=scheme_kpi,
                    min_achievement_pct=tier['min_achievement_pct'],
                    max_achievement_pct=tier.get('max_achievement_pct'),
                    multiplier=tier['multiplier'],
                )
                for tier in row['tiers']
            ])

    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> IncentiveScheme:
        errors = SchemeService.validate_config(data)
        if errors:
            raise BusinessError('; '.join(errors))
        if IncentiveScheme.objects.filter(code=data['code'], is_current=True).exists():
            raise BusinessError(f"A scheme with code '{data['code']}' already exists.")

        kpi_rows = data.pop('kpis')
        gate_rows = data.pop('gates', [])
        scheme = IncentiveScheme.objects.create(**data)
        SchemeService._save_children(scheme, kpi_rows, gate_rows)
        AuditService.log('create', 'incentives.IncentiveScheme', scheme.pk, actor,
                         {'code': scheme.code, 'version': scheme.version})
        return scheme

    @staticmethod
    @transaction.atomic
    def update(scheme: IncentiveScheme, data: dict, actor=None) -> IncentiveScheme:
        """Create a new version of the scheme; children are re-created on the new row."""
        errors = SchemeService.validate_config(data)
        if errors:
            raise BusinessError('; '.join(errors))
        if data.get('code', scheme.code) != scheme.code:
            raise BusinessError('Scheme code cannot be changed; create a new scheme instead.')

        kpi_rows = data.pop('kpis')
        gate_rows = data.pop('gates', [])
        old_version = scheme.version
        data.pop('effective_from', None)  # create_new_version sets effective dates
        scheme = scheme.create_new_version(**data)
        SchemeService._save_children(scheme, kpi_rows, gate_rows)
        AuditService.log('update', 'incentives.IncentiveScheme', scheme.pk, actor,
                         {'code': scheme.code, 'from_version': old_version,
                          'to_version': scheme.version})
        return scheme

    @staticmethod
    def deactivate(scheme: IncentiveScheme, actor=None) -> None:
        scheme.is_active = False
        scheme.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('deactivate', 'incentives.IncentiveScheme', scheme.pk, actor,
                         {'code': scheme.code})

    @staticmethod
    def sip_structure() -> list[dict]:
        """Current schemes grouped by (entity type × channel) as SIP components.
        A complete SIP has components whose vp_basis_pct sum to exactly 100 (e.g.
        monthly 80 + annual 20). Completeness is advisory — a single 100% monthly
        scheme is equally valid."""
        schemes = (
            IncentiveScheme.objects.filter(is_current=True, is_active=True)
            .select_related('target_entity_type', 'channel')
            .prefetch_related('kpis')
            .order_by('code')
        )
        groups: dict[tuple, dict] = {}
        for s in schemes:
            key = (s.target_entity_type_id, s.channel_id)
            g = groups.setdefault(key, {
                'entity_type': s.target_entity_type.code,
                'entity_type_name': s.target_entity_type.name,
                'channel': s.channel.code if s.channel_id else None,
                'components': [],
                'total_vp_basis_pct': Decimal('0'),
            })
            g['components'].append({
                'scheme_id': s.pk,
                'scheme_code': s.code,
                'scheme_name': s.name,
                'payout_frequency': s.payout_frequency,
                'vp_basis_pct': str(s.vp_basis_pct),
                'kpi_count': len(s.kpis.all()),
            })
            g['total_vp_basis_pct'] += s.vp_basis_pct
        out = []
        for g in groups.values():
            g['is_complete'] = g['total_vp_basis_pct'] == Decimal('100.00')
            g['total_vp_basis_pct'] = str(g['total_vp_basis_pct'])
            out.append(g)
        return sorted(out, key=lambda x: (x['entity_type'], x['channel'] or ''))

    @staticmethod
    def build_engine_input(scheme: IncentiveScheme) -> engine.SchemeInput:
        kpis = []
        for skpi in scheme.kpis.select_related('kpi').prefetch_related('tiers').order_by(
            'display_order', 'id',
        ):
            kpis.append(engine.SchemeKPIInput(
                kpi_code=skpi.kpi.code,
                category=skpi.incentive_category,
                weightage=skpi.weightage,
                min_qualifying_pct=skpi.min_qualifying_pct,
                multiplier_cap=skpi.multiplier_cap,
                tiers=tuple(
                    engine.TierInput(t.min_achievement_pct, t.max_achievement_pct, t.multiplier)
                    for t in sorted(skpi.tiers.all(), key=lambda t: t.min_achievement_pct)
                ),
            ))
        return engine.SchemeInput(
            code=scheme.code,
            vp_basis_pct=scheme.vp_basis_pct,
            overall_cap_pct=scheme.overall_cap_pct,
            gates=tuple(
                engine.GateInput(g.kpi.code, g.operator, g.threshold_pct)
                for g in scheme.gates.select_related('kpi').order_by('display_order', 'id')
            ),
            gatekeeper_action=scheme.gatekeeper_action,
            kpis=tuple(kpis),
        )

    @staticmethod
    def config_snapshot(scheme_input: engine.SchemeInput, scheme: IncentiveScheme,
                        period) -> dict:
        """JSON-serializable snapshot of every config value the engine will use."""
        return {
            'scheme_code': scheme.code,
            'scheme_version': scheme.version,
            'vp_basis_pct': str(scheme_input.vp_basis_pct),
            'overall_cap_pct': str(scheme_input.overall_cap_pct)
                               if scheme_input.overall_cap_pct is not None else None,
            'gates': [
                {'kpi_code': g.kpi_code, 'operator': g.operator,
                 'threshold_pct': str(g.threshold_pct)}
                for g in scheme_input.gates
            ],
            'gatekeeper_action': scheme_input.gatekeeper_action,
            'period_code': period.code,
            'period_working_days': period.working_days,
            'kpis': [
                {
                    'kpi_code': k.kpi_code,
                    'category': k.category,
                    'weightage': str(k.weightage),
                    'min_qualifying_pct': str(k.min_qualifying_pct)
                                          if k.min_qualifying_pct is not None else None,
                    'multiplier_cap': str(k.multiplier_cap)
                                      if k.multiplier_cap is not None else None,
                    'tiers': [
                        {'min': str(t.min_pct),
                         'max': str(t.max_pct) if t.max_pct is not None else None,
                         'multiplier': str(t.multiplier)}
                        for t in k.tiers
                    ],
                }
                for k in scheme_input.kpis
            ],
        }


class VariablePayService:

    @staticmethod
    def upsert(entity, target_period, amount: Decimal, eligible_working_days=None,
               source=VariablePay.MANUAL, actor=None) -> VariablePay:
        if amount < 0:
            raise BusinessError('Variable pay amount cannot be negative.')
        if eligible_working_days is not None:
            if not target_period.working_days:
                raise BusinessError(
                    'The period has no working_days configured; cannot prorate.'
                )
            if eligible_working_days > target_period.working_days:
                raise BusinessError(
                    f'eligible_working_days ({eligible_working_days}) exceeds the period '
                    f'working days ({target_period.working_days}).'
                )
        vp, created = VariablePay.objects.update_or_create(
            entity=entity, target_period=target_period,
            defaults={'amount': amount, 'eligible_working_days': eligible_working_days,
                      'source': source, 'is_active': True},
        )
        AuditService.log('create' if created else 'update', 'incentives.VariablePay',
                         vp.pk, actor,
                         {'entity_id': entity.pk, 'period_id': target_period.pk,
                          'amount': str(amount),
                          'eligible_working_days': eligible_working_days})
        return vp

    @staticmethod
    @transaction.atomic
    def bulk_import(rows: list[dict], target_period, actor=None) -> dict:
        """All-or-nothing import. Rows: [{entity_code, amount, eligible_working_days?}]."""
        from apps.hierarchy.models import Node

        errors = []
        resolved = []
        codes = [r.get('entity_code', '') for r in rows]
        entities = {
            e.code: e for e in Node.objects.filter(code__in=codes, is_current=True)
        }
        for i, row in enumerate(rows, start=1):
            entity = entities.get(row.get('entity_code', ''))
            if entity is None:
                errors.append({'row': i, 'errors': [f"Unknown entity code '{row.get('entity_code')}'."]})
                continue
            try:
                amount = Decimal(str(row['amount']))
            except Exception:
                errors.append({'row': i, 'errors': ['Invalid amount.']})
                continue
            if amount < 0:
                errors.append({'row': i, 'errors': ['Amount cannot be negative.']})
                continue
            days = row.get('eligible_working_days')
            if days is not None:
                try:
                    days = int(days)
                except (TypeError, ValueError):
                    errors.append({'row': i, 'errors': ['Invalid eligible_working_days.']})
                    continue
                if days < 0:
                    errors.append({'row': i, 'errors': ['eligible_working_days cannot be negative.']})
                    continue
                if not target_period.working_days or days > target_period.working_days:
                    errors.append({'row': i, 'errors': ['eligible_working_days exceeds period working days.']})
                    continue
            resolved.append((entity, amount, days))

        if errors:
            return {'created': 0, 'updated': 0, 'errors': errors}

        created = updated = 0
        for entity, amount, days in resolved:
            _, was_created = VariablePay.objects.update_or_create(
                entity=entity, target_period=target_period,
                defaults={'amount': amount, 'eligible_working_days': days,
                          'source': VariablePay.BULK_IMPORT, 'is_active': True},
            )
            created += was_created
            updated += not was_created
        AuditService.log('bulk_import', 'incentives.VariablePay', 0, actor,
                         {'period_id': target_period.pk, 'created': created, 'updated': updated})
        return {'created': created, 'updated': updated, 'errors': []}


class ExceptionService:

    @staticmethod
    def effect_months(duration_config: dict, reference_date=None) -> int:
        """Total monthly periods an exception covers (including the requested one).
        Pure config interpretation — see ExceptionCategory.duration_config shapes."""
        cfg = duration_config or {}
        ctype = cfg.get('type')
        if ctype == 'fixed':
            return max(1, int(cfg.get('effect_months', 1)))
        if ctype == 'join_day_cutoff':
            if reference_date is None:
                raise BusinessError(
                    'This exception reason needs a reference date (e.g. the joining date).'
                )
            if reference_date.day <= int(cfg.get('cutoff_day', 15)):
                return max(1, int(cfg.get('months_on_or_before', 2)))
            return max(1, int(cfg.get('months_after', 3)))
        return 1

    @staticmethod
    def _following_monthly_periods(period, count: int) -> list:
        """The next ``count`` contiguous monthly TargetPeriods after ``period``.
        Raises naming the missing months, so approvers are never surprised later."""
        from apps.targets.models import TargetPeriod

        following = list(TargetPeriod.objects.filter(
            period_type=TargetPeriod.MONTHLY, start_date__gt=period.start_date,
            is_active=True,
        ).order_by('start_date')[:count])

        expected = period.start_date
        resolved = []
        for i in range(count):
            # First of the next month, robust across year ends.
            expected = (expected.replace(day=1) + timedelta(days=32)).replace(day=1)
            match = next((p for p in following if p.start_date == expected), None)
            if match is None:
                raise BusinessError(
                    f'This exception covers {count + 1} months, but no monthly period '
                    f'starting {expected.isoformat()} exists yet. Create the planning '
                    f'periods first (Planning Calendar).'
                )
            resolved.append(match)
        return resolved

    @staticmethod
    def create(data: dict, actor=None) -> PayoutException:
        entity = data['entity']
        period = data['target_period']
        scheme = data.get('scheme')
        if scheme is not None and scheme.target_entity_type_id != entity.entity_type_id:
            raise BusinessError(
                'The entity is not of the scheme\'s target entity type.'
            )
        live = PayoutException.objects.filter(
            entity=entity, target_period=period, scheme=scheme, is_active=True,
        ).exclude(status=PayoutException.REJECTED)
        if live.exists():
            raise BusinessError(
                'A live exception already exists for this entity, period and scheme.'
            )

        # Resolve the catalog entry for the reason and pre-fill any treatment the maker
        # left at its default with the category's configured default.
        cat = None
        code = (data.get('category') or '').strip()
        if code:
            cat = ExceptionCategory.objects.filter(
                code=code, is_current=True, is_active=True,
            ).first()
        if cat is not None:
            if cat.channel_id is not None and entity.channel_id != cat.channel_id:
                raise BusinessError(
                    f'Reason "{cat.name}" applies to the {cat.channel.code} channel only.'
                )
            if data.get('sales_kpi_action', PayoutException.ACTUAL) == PayoutException.ACTUAL:
                data['sales_kpi_action'] = cat.default_sales_kpi_action
            if data.get('execution_kpi_action', PayoutException.ACTUAL) == PayoutException.ACTUAL:
                data['execution_kpi_action'] = cat.default_execution_kpi_action
            if data.get('gatekeeper_action', PayoutException.NO_EXEMPTION) == PayoutException.NO_EXEMPTION:
                data['gatekeeper_action'] = cat.default_gatekeeper_action
            # Duration is resolved (and its period coverage validated) at CREATE time,
            # so approval can never fail on missing periods.
            months = ExceptionService.effect_months(
                cat.duration_config, data.get('reference_date'),
            )
            if months > 1:
                ExceptionService._following_monthly_periods(period, months - 1)

        exc = PayoutException.objects.create(requested_by=actor, category_ref=cat, **data)
        AuditService.log('create', 'incentives.PayoutException', exc.pk, actor,
                         {'entity_id': entity.pk, 'period_id': period.pk,
                          'category': exc.category})
        ExceptionService._maybe_start_workflow(exc, cat, actor)
        ExceptionService._notify_raised(exc)
        return exc

    @staticmethod
    def update_pending(exc: PayoutException, data: dict, actor=None) -> PayoutException:
        """Maker edits a pending request. Re-runs the create-time validations against the
        merged values, keeps ``category_ref`` in sync when the reason changes, and audits."""
        if exc.status != PayoutException.PENDING:
            raise BusinessError('Only pending exceptions can be edited.')
        entity = data.get('entity', exc.entity)
        period = data.get('target_period', exc.target_period)
        scheme = data.get('scheme', exc.scheme)
        if scheme is not None and scheme.target_entity_type_id != entity.entity_type_id:
            raise BusinessError('The entity is not of the scheme\'s target entity type.')
        clash = PayoutException.objects.filter(
            entity=entity, target_period=period, scheme=scheme, is_active=True,
        ).exclude(status=PayoutException.REJECTED).exclude(pk=exc.pk)
        if clash.exists():
            raise BusinessError(
                'A live exception already exists for this entity, period and scheme.'
            )

        cat = exc.category_ref
        if 'category' in data:
            code = (data.get('category') or '').strip()
            data['category'] = code
            cat = ExceptionCategory.objects.filter(
                code=code, is_current=True, is_active=True,
            ).first() if code else None
            exc.category_ref = cat
        if cat is not None:
            if cat.channel_id is not None and entity.channel_id != cat.channel_id:
                raise BusinessError(
                    f'Reason "{cat.name}" applies to the {cat.channel.code} channel only.'
                )
            months = ExceptionService.effect_months(
                cat.duration_config, data.get('reference_date', exc.reference_date),
            )
            if months > 1:
                ExceptionService._following_monthly_periods(period, months - 1)

        for field, value in data.items():
            setattr(exc, field, value)
        exc.save()
        AuditService.log('update', 'incentives.PayoutException', exc.pk, actor,
                         {'fields': sorted(data.keys())})
        return exc

    @staticmethod
    def _notify_raised(exc: PayoutException) -> None:
        """Notify the checker an exception needs review. When a workflow governs the request,
        its step activation already emits ``workflow_pending`` — so we only send the dedicated
        ``exception_raised`` copy on the legacy direct maker-checker path."""
        from apps.workflows.services import WorkflowService
        from apps.workflows import routing
        from .notifications import notify_exception_raised

        if WorkflowService.for_subject('incentives.PayoutException', exc.pk) is not None:
            return  # workflow path notifies the assignee via workflow_pending
        checker = routing.manager_at_level(exc.entity, 1)
        if checker:
            notify_exception_raised(exc, checker[0])

    @staticmethod
    def approve(exc: PayoutException, actor) -> PayoutException:
        """Approve through the governing workflow when one is configured; otherwise a direct
        single-step maker-checker (used when workflows aren't seeded)."""
        from apps.workflows.models import WorkflowInstance
        from apps.workflows.services import WorkflowService

        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        if inst is not None and inst.status in WorkflowInstance.OPEN_STATUSES:
            WorkflowService.approve(inst, actor)
            exc.refresh_from_db()
            return exc  # workflow path notifies the raiser via workflow_resolved

        if exc.status != PayoutException.PENDING:
            raise BusinessError(f'Only pending exceptions can be approved (status: {exc.status}).')
        if exc.requested_by_id is not None and actor is not None and exc.requested_by_id == actor.pk:
            raise BusinessError('An exception cannot be approved by its requester (maker-checker).')
        exc.status = PayoutException.APPROVED
        exc.approved_by = actor
        exc.approved_at = timezone.now()
        exc.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        AuditService.log('approve', 'incentives.PayoutException', exc.pk, actor, {})
        ExceptionService.materialize_children(exc)
        ExceptionService._notify_resolved_if_terminal(exc)
        return exc

    @staticmethod
    def materialize_children(exc: PayoutException) -> int:
        """On approval of a multi-month exception, create one APPROVED child per
        following monthly period. Children are ordinary exception rows — the payout
        engine's per-period lookup and the uniqueness constraints stay untouched —
        each auditable and individually revocable by a checker."""
        cat = exc.category_ref
        if cat is None or exc.parent_id is not None:
            return 0
        months = ExceptionService.effect_months(cat.duration_config, exc.reference_date)
        if months <= 1:
            return 0
        created = 0
        for p in ExceptionService._following_monthly_periods(exc.target_period, months - 1):
            clash = PayoutException.objects.filter(
                entity=exc.entity, target_period=p, scheme=exc.scheme, is_active=True,
            ).exclude(status=PayoutException.REJECTED).exists()
            if clash:
                continue  # an explicit exception already covers that period — it wins
            PayoutException.objects.create(
                entity=exc.entity, target_period=p, scheme=exc.scheme,
                category=exc.category, category_ref=cat,
                sales_kpi_action=exc.sales_kpi_action,
                execution_kpi_action=exc.execution_kpi_action,
                gatekeeper_action=exc.gatekeeper_action,
                reason=exc.reason, status=PayoutException.APPROVED,
                requested_by=exc.requested_by, approved_by=exc.approved_by,
                approved_at=exc.approved_at, parent=exc,
                reference_date=exc.reference_date,
            )
            created += 1
        if created:
            AuditService.log(
                'materialize', 'incentives.PayoutException', exc.pk, exc.approved_by,
                {'children_created': created, 'category': exc.category},
            )
        return created

    @staticmethod
    def _notify_resolved_if_terminal(exc: PayoutException) -> None:
        """Notify the raiser when a *direct* maker-checker action reaches a terminal status.
        The workflow-governed path is covered by ``workflow_resolved`` instead, so this is only
        called on the legacy direct branch."""
        if exc.status in (PayoutException.APPROVED, PayoutException.REJECTED):
            from .notifications import notify_exception_resolved
            notify_exception_resolved(exc)

    @staticmethod
    def reject(exc: PayoutException, actor, reason: str) -> PayoutException:
        from apps.workflows.models import WorkflowInstance
        from apps.workflows.services import WorkflowService

        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        if inst is not None and inst.status in WorkflowInstance.OPEN_STATUSES:
            WorkflowService.reject(inst, actor, reason)
            exc.refresh_from_db()
            return exc  # workflow path notifies the raiser via workflow_resolved

        if exc.status != PayoutException.PENDING:
            raise BusinessError(f'Only pending exceptions can be rejected (status: {exc.status}).')
        exc.status = PayoutException.REJECTED
        exc.rejection_reason = reason
        # approved_by/approved_at are the decision columns, not approval-only ones: a
        # rejection that records no decider leaves the request unaccountable.
        exc.approved_by = actor
        exc.approved_at = timezone.now()
        exc.save(update_fields=['status', 'rejection_reason', 'approved_by', 'approved_at',
                                'updated_at'])
        AuditService.log('reject', 'incentives.PayoutException', exc.pk, actor,
                         {'reason': reason})
        ExceptionService._notify_resolved_if_terminal(exc)
        return exc

    @staticmethod
    def withdraw(exc: PayoutException, actor=None) -> None:
        """Maker withdraws a pending request — cancels its workflow then soft-deletes."""
        from apps.workflows.models import WorkflowInstance
        from apps.workflows.services import WorkflowService

        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        if inst is not None and inst.status in WorkflowInstance.OPEN_STATUSES:
            WorkflowService.cancel(inst, actor, reason='Withdrawn by requester')
        exc.is_active = False
        exc.save(update_fields=['is_active', 'updated_at'])
        # Auto-materialized children stand or fall with their parent.
        exc.children.filter(is_active=True).update(is_active=False)

    @staticmethod
    def _maybe_start_workflow(exc: PayoutException, cat, actor) -> None:
        from apps.workflows.models import WorkflowDefinition
        from apps.workflows.services import WorkflowService

        code = (cat.workflow_definition_code if cat and cat.workflow_definition_code
                else DEFAULT_EXCEPTION_WORKFLOW)
        if not WorkflowDefinition.objects.filter(
            code=code, is_current=True, is_active=True,
        ).exists():
            return  # workflows not configured → legacy direct maker-checker applies
        impact = ExceptionService.estimate_impact(exc)
        WorkflowService.initiate(
            exc, code, initiated_by=actor,
            context_overrides={
                'impact_amount': str(impact) if impact is not None else None,
            },
        )

    @staticmethod
    def estimate_impact(exc: PayoutException):
        """Best-effort payout delta (with the override vs actuals) for ``exc``'s entity in its
        period, summed across applicable schemes. Returns ``Decimal`` or ``None`` when the
        inputs to compute a payout (variable pay / achievements / scheme) aren't present yet."""
        try:
            from apps.achievements.models import Achievement

            entity, period = exc.entity, exc.target_period
            schemes = ([exc.scheme] if exc.scheme_id else list(
                IncentiveScheme.objects.filter(
                    target_entity_type=entity.entity_type, is_current=True, is_active=True,
                )
            ))
            if not schemes:
                return None
            total = Decimal('0.00')
            computed_any = False
            for scheme in schemes:
                vp = VariablePay.objects.filter(
                    target_period=period, entity=entity, is_active=True,
                ).first()
                if vp is None:
                    continue
                si = SchemeService.build_engine_input(scheme)
                kpi_codes = {k.kpi_code for k in si.kpis}
                kpi_codes.update(g.kpi_code for g in si.gates)
                ach: dict[str, engine.AchievementInput] = {}
                for a in Achievement.objects.filter(
                    target_period=period, entity=entity, kpi__code__in=kpi_codes,
                ).select_related('kpi'):
                    code = a.kpi.code
                    # scheme-channel row wins, else keep first seen.
                    if code not in ach or a.channel_id == scheme.channel_id:
                        ach[code] = engine.AchievementInput(
                            a.achievement_pct, a.target_value, a.achieved_value,
                        )
                common = dict(
                    entity_id=entity.pk, variable_pay=vp.amount,
                    eligible_working_days=vp.eligible_working_days,
                    period_working_days=period.working_days or 0, achievements=ach,
                )
                base = engine.compute_entity(si, engine.NodeInput(exception=None, **common))
                withx = engine.compute_entity(si, engine.NodeInput(
                    exception=engine.ExceptionInput(
                        exc.sales_kpi_action, exc.execution_kpi_action, exc.gatekeeper_action,
                    ), **common,
                ))
                total += (withx.total_payout - base.total_payout)
                computed_any = True
            return total if computed_any else None
        except Exception:  # noqa: BLE001 — impact is advisory; never block raising an exception
            return None

    @staticmethod
    def approved_for(period, scheme) -> dict[int, PayoutException]:
        """entity_id → approved exception, with scheme-specific rows overriding
        scheme-null (all-schemes) rows."""
        result: dict[int, PayoutException] = {}
        qs = list(PayoutException.objects.filter(
            target_period=period, status=PayoutException.APPROVED, is_active=True,
        ).filter(Q(scheme__isnull=True) | Q(scheme=scheme)))
        # Two-pass so precedence is explicit regardless of DB null ordering.
        for exc in qs:
            if exc.scheme_id is None:
                result.setdefault(exc.entity_id, exc)
        for exc in qs:
            if exc.scheme_id is not None:
                result[exc.entity_id] = exc
        return result


class PayoutService:

    # action → set of statuses it is allowed from
    TRANSITIONS = {
        'submit': {PayoutRun.COMPUTED},
        'approve': {PayoutRun.UNDER_REVIEW},
        'reject': {PayoutRun.UNDER_REVIEW},
        'mark_paid': {PayoutRun.APPROVED},
    }

    @staticmethod
    def _assert_transition(run: PayoutRun, action: str) -> None:
        allowed = PayoutService.TRANSITIONS[action]
        if run.status not in allowed:
            raise BusinessError(
                f"Cannot {action.replace('_', ' ')} a run in status '{run.status}'."
            )

    # ── run lifecycle ───────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def start_run(scheme_id: int, period_id: int, actor=None,
                  kind: str = PayoutRun.FINAL, cycle=None) -> PayoutRun:
        from apps.targets.models import TargetPeriod

        scheme = IncentiveScheme.objects.get(pk=scheme_id, is_current=True, is_active=True)
        period = TargetPeriod.objects.get(pk=period_id)
        # The scheme's SIP component decides which period type its runs compute against:
        # monthly KPIs scheme → monthly periods, annual-performance scheme → the annual period.
        expected = (
            TargetPeriod.ANNUAL if scheme.payout_frequency == IncentiveScheme.ANNUAL
            else TargetPeriod.MONTHLY
        )
        if period.period_type != expected:
            raise BusinessError(
                f'{scheme.code} is a {scheme.payout_frequency} scheme — runs compute '
                f'against {expected} periods, not {period.period_type}.'
            )

        # One live run per scheme CODE × period × kind (a new scheme version is a new FK id).
        # Estimate and final runs coexist; a run only supersedes a prior run of its own kind.
        existing = PayoutRun.objects.filter(
            scheme__code=scheme.code, target_period=period, kind=kind,
            status__in=PayoutRun.LIVE_STATUSES,
        ).select_for_update()
        for run in existing:
            # Estimates auto-supersede; a blocking final run must be cleared first.
            if kind != PayoutRun.ESTIMATE and run.status in PayoutRun.BLOCKING_STATUSES:
                raise BusinessError(
                    f'A {kind} run for {scheme.code}@{period.code} is {run.status}; '
                    f'it must be rejected/completed before recomputing.'
                )
            run.status = PayoutRun.SUPERSEDED
            run.save(update_fields=['status', 'updated_at'])
            AuditService.log('supersede', 'incentives.PayoutRun', run.pk, actor, {})

        run = PayoutRun.objects.create(
            scheme=scheme, target_period=period, status=PayoutRun.COMPUTING,
            kind=kind, cycle=cycle, triggered_by=actor,
        )
        AuditService.log('create', 'incentives.PayoutRun', run.pk, actor,
                         {'scheme': scheme.code, 'period': period.code, 'kind': kind})
        return run

    @staticmethod
    def _achievement_map(scheme, period, entity_ids, kpi_codes) -> dict:
        """{(entity_id, kpi_code): AchievementInput} for a scheme over a period. Achievements
        may be channel-dimensioned; per (entity, kpi) precedence is the scheme-channel row >
        the channel-null (overall) row > an aggregate of the channel rows."""
        from apps.achievements.models import Achievement

        rows_by_key: dict[tuple[int, str], list] = {}
        for a in Achievement.objects.filter(
            target_period=period, entity_id__in=entity_ids, kpi__code__in=kpi_codes,
        ).select_related('kpi'):
            rows_by_key.setdefault((a.entity_id, a.kpi.code), []).append(a)
        result: dict[tuple[int, str], engine.AchievementInput] = {}
        for key, rows in rows_by_key.items():
            chosen = None
            if scheme.channel_id:
                chosen = next((a for a in rows if a.channel_id == scheme.channel_id), None)
            if chosen is None:
                chosen = next((a for a in rows if a.channel_id is None), None)
            if chosen is not None:
                result[key] = engine.AchievementInput(
                    chosen.achievement_pct, chosen.target_value, chosen.achieved_value,
                )
                continue
            if scheme.channel_id:
                continue  # channel-scoped scheme: rows for other channels don't count
            target = sum((a.target_value for a in rows), Decimal('0'))
            achieved = sum((a.achieved_value for a in rows), Decimal('0'))
            pct = (
                (achieved / target * _HUNDRED).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                if target else Decimal('0.00')
            )
            result[key] = engine.AchievementInput(pct, target, achieved)
        return result

    @staticmethod
    @transaction.atomic
    def compute_run(run_id: int, triggered_by=None) -> dict:
        from apps.hierarchy.models import Node

        run = PayoutRun.objects.select_related('scheme', 'target_period').get(pk=run_id)
        scheme, period = run.scheme, run.target_period
        scheme_input = SchemeService.build_engine_input(scheme)

        log = ComputationLog.objects.create(
            computation_type='payout',
            entity_id=0,  # plan-wide
            period_id=period.pk,
            triggered_by_id=triggered_by.pk if triggered_by else None,
            config_snapshot=SchemeService.config_snapshot(scheme_input, scheme, period),
            result_snapshot={},
        )

        # Eligible entities
        entities = Node.objects.filter(
            entity_type__code=scheme.target_entity_type.code,
            is_current=True, is_active=True, status='active',
        )
        if scheme.channel_id:
            entities = entities.filter(channel_id=scheme.channel_id)
        entities = list(entities.only('id', 'name'))
        entity_ids = [e.pk for e in entities]

        # Bulk-load inputs
        vp_map = {
            vp.entity_id: vp
            for vp in VariablePay.objects.filter(
                target_period=period, entity_id__in=entity_ids, is_active=True,
            )
        }
        kpi_codes = {k.kpi_code for k in scheme_input.kpis}
        kpi_codes.update(g.kpi_code for g in scheme_input.gates)
        achievement_map = PayoutService._achievement_map(scheme, period, entity_ids, kpi_codes)
        exception_map = ExceptionService.approved_for(period, scheme)
        scheme_kpi_by_code = {
            skpi.kpi.code: skpi for skpi in scheme.kpis.select_related('kpi')
        }

        errors: list[dict] = []
        total = Decimal('0.00')
        processed = 0
        paid_targets: list = []
        for entity in entities:
            vp = vp_map.get(entity.pk)
            if vp is None:
                errors.append({'entity_id': entity.pk, 'entity_name': entity.name,
                               'code': 'no_variable_pay',
                               'error': 'No variable pay configured for this period.'})
                continue
            exc = exception_map.get(entity.pk)
            result = engine.compute_entity(scheme_input, engine.NodeInput(
                entity_id=entity.pk,
                variable_pay=vp.amount,
                eligible_working_days=vp.eligible_working_days,
                period_working_days=period.working_days or 0,
                achievements={
                    code: achievement_map[(entity.pk, code)]
                    for code in kpi_codes if (entity.pk, code) in achievement_map
                },
                exception=engine.ExceptionInput(
                    exc.sales_kpi_action, exc.execution_kpi_action, exc.gatekeeper_action,
                ) if exc else None,
            ))
            payout = Payout.objects.create(
                run=run, scheme=scheme, target_period=period, entity=entity,
                variable_pay_amount=vp.amount,
                proration_factor=result.proration_factor,
                eligible_vp=result.eligible_vp,
                gatekeeper_status=result.gatekeeper_status,
                gate_results=[
                    {'kpi_code': g.kpi_code, 'achievement_pct': str(g.achievement_pct),
                     'operator': g.operator, 'threshold_pct': str(g.threshold_pct),
                     'passed': g.passed}
                    for g in result.gate_results
                ],
                exception=exc,
                gross_payout=result.gross_payout,
                capped=result.capped,
                total_payout=result.total_payout,
                total_multiplier=result.total_multiplier,
                computation_id=log.pk,
            )
            PayoutLineItem.objects.bulk_create([
                PayoutLineItem(
                    payout=payout,
                    scheme_kpi=scheme_kpi_by_code[line.kpi_code],
                    kpi_code=line.kpi_code,
                    target_value=line.target_value,
                    achieved_value=line.achieved_value,
                    achievement_pct=line.achievement_pct,
                    tier_min=line.tier_min,
                    tier_max=line.tier_max,
                    base_multiplier=line.base_multiplier,
                    applied_multiplier=line.applied_multiplier,
                    weightage=line.weightage,
                    weighted_multiplier=line.weighted_multiplier,
                    line_payout=line.line_payout,
                    treatment=line.treatment,
                    display_order=order,
                )
                for order, line in enumerate(result.lines)
            ])
            total += result.total_payout
            paid_targets.append((entity, result.total_payout))
            processed += 1

        run.status = PayoutRun.COMPUTED
        run.computation_log_id = log.pk
        run.entities_processed = processed
        run.error_count = len(errors)
        run.errors = errors
        run.total_payout = total
        run.save(update_fields=[
            'status', 'computation_log_id', 'entities_processed', 'error_count',
            'errors', 'total_payout', 'updated_at',
        ])
        log.result_snapshot = {
            'run_id': run.pk, 'entities_processed': processed,
            'total_payout': str(total), 'error_count': len(errors),
        }
        log.save(update_fields=['result_snapshot'])

        # Only final runs notify payees — the nightly estimate would spam every payee
        # with a "payout ready" that isn't.
        if run.kind == PayoutRun.FINAL:
            from .notifications import notify_payout_ready
            notify_payout_ready(run, paid_targets)

        return {'run_id': run.pk, 'computation_id': log.pk,
                'entities_processed': processed, 'total_payout': str(total),
                'errors': errors}

    @staticmethod
    @transaction.atomic
    def compute_adjustment_run(run_id: int, triggered_by=None) -> dict:
        """Recompute a scheme off the reference month's *current* (restated) achievements and
        store, per payee, the delta vs what was already paid — the arrears/recovery that rides
        the current cycle. The paid run is never touched; only entities whose number changed
        get a row."""
        from apps.hierarchy.models import Node

        run = PayoutRun.objects.select_related(
            'scheme', 'target_period', 'reference_run', 'reference_run__target_period',
        ).get(pk=run_id)
        scheme = run.scheme
        reference_run = run.reference_run
        ach_period = reference_run.target_period  # the month being trued up
        scheme_input = SchemeService.build_engine_input(scheme)

        log = ComputationLog.objects.create(
            computation_type='payout_adjustment',
            entity_id=0,
            period_id=run.target_period_id,
            triggered_by_id=triggered_by.pk if triggered_by else None,
            config_snapshot={
                **SchemeService.config_snapshot(scheme_input, scheme, ach_period),
                'reference_run_id': reference_run.pk,
                'reference_computation_id': reference_run.computation_log_id,
                'achievement_period_code': ach_period.code,
            },
            result_snapshot={},
        )

        entities = Node.objects.filter(
            entity_type__code=scheme.target_entity_type.code,
            is_current=True, is_active=True, status='active',
        )
        if scheme.channel_id:
            entities = entities.filter(channel_id=scheme.channel_id)
        entities = list(entities.only('id'))
        entity_ids = [e.pk for e in entities]

        # What each payee has actually received for the reference month so far: the
        # reference run's disbursed amounts (a HELD payout was excluded from the register —
        # nothing was paid; the adjustment is how it finally pays) plus the deltas of any
        # prior live adjustment against the same run (so repeated adjustments never re-pay
        # an already-settled delta).
        reference_paid = {
            p.entity_id: (Decimal('0.00') if p.hold_status == Payout.HOLD_HELD
                          else p.total_payout)
            for p in reference_run.payouts.all()
        }
        for p in Payout.objects.filter(
            run__reference_run=reference_run, run__kind=PayoutRun.ADJUSTMENT,
            run__status__in=PayoutRun.LIVE_STATUSES,
        ).exclude(run_id=run.pk):
            reference_paid[p.entity_id] = (
                reference_paid.get(p.entity_id, Decimal('0.00')) + p.adjustment_amount
            )
        # Anyone paid before OR eligible now can move; union so recoveries aren't missed.
        candidate_ids = set(entity_ids) | set(reference_paid)
        entity_by_id = {e.pk: e for e in entities}
        for eid in reference_paid:
            if eid not in entity_by_id:
                node = Node.objects.filter(pk=eid).only('id').first()
                if node is not None:
                    entity_by_id[eid] = node

        vp_map = {
            vp.entity_id: vp for vp in VariablePay.objects.filter(
                target_period=ach_period, entity_id__in=candidate_ids, is_active=True,
            )
        }
        kpi_codes = {k.kpi_code for k in scheme_input.kpis}
        kpi_codes.update(g.kpi_code for g in scheme_input.gates)
        achievement_map = PayoutService._achievement_map(scheme, ach_period, candidate_ids, kpi_codes)
        exception_map = ExceptionService.approved_for(ach_period, scheme)
        scheme_kpi_by_code = {skpi.kpi.code: skpi for skpi in scheme.kpis.select_related('kpi')}

        net_delta = Decimal('0.00')
        processed = 0
        arrears_targets: list = []
        for eid in candidate_ids:
            entity = entity_by_id.get(eid)
            if entity is None:
                continue
            ref_paid = reference_paid.get(eid, Decimal('0.00'))
            vp = vp_map.get(eid)
            if vp is None:
                # No variable pay now → current earning is zero; a prior payment is recovered.
                if not ref_paid:
                    continue
                adjustment = Decimal('0.00') - ref_paid
                Payout.objects.create(
                    run=run, scheme=scheme, target_period=run.target_period, entity=entity,
                    variable_pay_amount=Decimal('0.00'), proration_factor=Decimal('1'),
                    eligible_vp=Decimal('0.00'), gatekeeper_status=Payout.NOT_APPLICABLE,
                    gross_payout=Decimal('0.00'), total_payout=Decimal('0.00'),
                    total_multiplier=Decimal('0'), adjustment_amount=adjustment,
                    computation_id=log.pk,
                )
                net_delta += adjustment
                processed += 1
                continue

            exc = exception_map.get(eid)
            result = engine.compute_entity(scheme_input, engine.NodeInput(
                entity_id=eid, variable_pay=vp.amount,
                eligible_working_days=vp.eligible_working_days,
                period_working_days=ach_period.working_days or 0,
                achievements={
                    code: achievement_map[(eid, code)]
                    for code in kpi_codes if (eid, code) in achievement_map
                },
                exception=engine.ExceptionInput(
                    exc.sales_kpi_action, exc.execution_kpi_action, exc.gatekeeper_action,
                ) if exc else None,
            ))
            adjustment = result.total_payout - ref_paid
            if adjustment == Decimal('0.00'):
                continue  # nothing changed for this payee — no row
            payout = Payout.objects.create(
                run=run, scheme=scheme, target_period=run.target_period, entity=entity,
                variable_pay_amount=vp.amount, proration_factor=result.proration_factor,
                eligible_vp=result.eligible_vp, gatekeeper_status=result.gatekeeper_status,
                gate_results=[
                    {'kpi_code': g.kpi_code, 'achievement_pct': str(g.achievement_pct),
                     'operator': g.operator, 'threshold_pct': str(g.threshold_pct),
                     'passed': g.passed}
                    for g in result.gate_results
                ],
                gross_payout=result.gross_payout, capped=result.capped,
                total_payout=result.total_payout, total_multiplier=result.total_multiplier,
                adjustment_amount=adjustment, computation_id=log.pk,
            )
            PayoutLineItem.objects.bulk_create([
                PayoutLineItem(
                    payout=payout, scheme_kpi=scheme_kpi_by_code[line.kpi_code],
                    kpi_code=line.kpi_code, target_value=line.target_value,
                    achieved_value=line.achieved_value, achievement_pct=line.achievement_pct,
                    tier_min=line.tier_min, tier_max=line.tier_max,
                    base_multiplier=line.base_multiplier, applied_multiplier=line.applied_multiplier,
                    weightage=line.weightage, weighted_multiplier=line.weighted_multiplier,
                    line_payout=line.line_payout, treatment=line.treatment, display_order=order,
                )
                for order, line in enumerate(result.lines)
            ])
            net_delta += adjustment
            arrears_targets.append((entity, adjustment))
            processed += 1

        run.status = PayoutRun.COMPUTED
        run.computation_log_id = log.pk
        run.entities_processed = processed
        run.total_payout = net_delta
        run.save(update_fields=['status', 'computation_log_id', 'entities_processed',
                                'total_payout', 'updated_at'])
        log.result_snapshot = {
            'run_id': run.pk, 'entities_processed': processed, 'net_delta': str(net_delta),
            'reference_run_id': reference_run.pk,
        }
        log.save(update_fields=['result_snapshot'])
        return {'run_id': run.pk, 'computation_id': log.pk, 'entities_processed': processed,
                'net_delta': str(net_delta)}

    @staticmethod
    def submit_for_review(run: PayoutRun, actor) -> PayoutRun:
        if run.kind != PayoutRun.FINAL:
            raise BusinessError(
                f'Only final payout runs enter review; a {run.kind} run cannot be submitted.'
            )
        if run.cycle_id is not None:
            # An individually-submitted run would be skipped by the cycle's approve/disburse
            # sweep (which moves computed runs) and strand its payouts on the register.
            raise BusinessError(
                'This run belongs to a payout cycle — submit and approve it through the cycle.'
            )
        PayoutService._assert_transition(run, 'submit')
        run.status = PayoutRun.UNDER_REVIEW
        run.submitted_by = actor
        run.submitted_at = timezone.now()
        run.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])
        AuditService.log('submit', 'incentives.PayoutRun', run.pk, actor, {})
        return run

    @staticmethod
    def approve(run: PayoutRun, actor) -> PayoutRun:
        PayoutService._assert_transition(run, 'approve')
        if run.submitted_by_id is not None and actor is not None and run.submitted_by_id == actor.pk:
            raise BusinessError('A run cannot be approved by its submitter (maker-checker).')
        run.status = PayoutRun.APPROVED
        run.approved_by = actor
        run.approved_at = timezone.now()
        run.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        AuditService.log('approve', 'incentives.PayoutRun', run.pk, actor, {})
        return run

    @staticmethod
    def reject(run: PayoutRun, actor, reason: str) -> PayoutRun:
        PayoutService._assert_transition(run, 'reject')
        run.status = PayoutRun.COMPUTED
        run.rejection_reason = reason
        run.submitted_by = None
        run.submitted_at = None
        run.save(update_fields=['status', 'rejection_reason', 'submitted_by',
                                'submitted_at', 'updated_at'])
        AuditService.log('reject', 'incentives.PayoutRun', run.pk, actor, {'reason': reason})
        return run

    @staticmethod
    def mark_paid(run: PayoutRun, actor, payment_ref: str = '') -> PayoutRun:
        PayoutService._assert_transition(run, 'mark_paid')
        run.status = PayoutRun.PAID
        run.paid_at = timezone.now()
        run.payment_ref = payment_ref
        run.save(update_fields=['status', 'paid_at', 'payment_ref', 'updated_at'])
        AuditService.log('mark_paid', 'incentives.PayoutRun', run.pk, actor,
                         {'payment_ref': payment_ref})
        return run

    @staticmethod
    def mark_failed(run_id: int, error: str) -> None:
        PayoutRun.objects.filter(pk=run_id).update(
            status=PayoutRun.FAILED, errors=[{'entity_id': 0, 'code': 'task_failed',
                                              'error': error}],
        )

    # ── reads ───────────────────────────────────────────────────────────────

    @staticmethod
    def breakdown(payout_id: int, user) -> Payout:
        payout = Payout.objects.select_related(
            'run', 'scheme', 'target_period', 'entity', 'exception',
        ).prefetch_related('line_items').get(pk=payout_id)
        if not requester_can_reach_entity(user, 'final_payout', payout.entity):
            raise BusinessError('You do not have access to this payout.')
        return payout

    @staticmethod
    def statement(payout_id: int, user) -> dict:
        """The per-payee statement: the self-explaining record a payee (or finance) reads —
        VP → gates → per-KPI multiplier lines → net, with hold and disbursement status.
        Access-controlled exactly like ``breakdown``."""
        p = PayoutService.breakdown(payout_id, user)
        return {
            'payout_id': p.pk,
            'entity': {'code': p.entity.code, 'name': p.entity.name},
            'period': {'code': p.target_period.code, 'name': p.target_period.name},
            'scheme': {'code': p.scheme.code, 'name': p.scheme.name, 'version': p.scheme.version},
            'variable_pay_amount': str(p.variable_pay_amount),
            'proration_factor': str(p.proration_factor),
            'eligible_vp': str(p.eligible_vp),
            'gatekeeper_status': p.gatekeeper_status,
            'gate_results': p.gate_results,
            'gross_payout': str(p.gross_payout),
            'capped': p.capped,
            'total_multiplier': str(p.total_multiplier),
            'total_payout': str(p.total_payout),
            'hold_status': p.hold_status,
            'hold_reason': p.hold_reason,
            'run_status': p.run.status,
            'payment_ref': p.run.payment_ref,
            'computation_id': p.computation_id,
            'lines': [
                {'kpi_code': li.kpi_code, 'achievement_pct': str(li.achievement_pct),
                 'applied_multiplier': str(li.applied_multiplier),
                 'weightage': str(li.weightage), 'weighted_multiplier': str(li.weighted_multiplier),
                 'line_payout': str(li.line_payout), 'treatment': li.treatment}
                for li in sorted(p.line_items.all(), key=lambda x: x.display_order)
            ],
        }

    @staticmethod
    def dashboard_info(period, entity, child_ids: list[int], user=None) -> dict:
        """Payload for the achievements dashboard graceful-degrade hooks.
        Aggregates the latest live runs of the period.

        Payout confidentiality (RFP access matrix): when ``user`` is given, payout
        amounts only appear where the user may see them — their own entity's payout
        always; someone else's (a drilled-down child, the team ranking) only at
        full/view_all on final_payout. A manager keeps the achievement ranking but
        never sees team payout amounts."""
        from apps.core.permissions import highest_level

        empty = {'available': False, 'estimated_payout': None, 'payout_kind': None,
                 'kpi_lines': {}, 'child_payouts': {}}
        if period is None:
            return empty
        live_statuses = [PayoutRun.COMPUTED, PayoutRun.UNDER_REVIEW,
                         PayoutRun.APPROVED, PayoutRun.PAID]
        # Prefer the cycle's final numbers; fall back to nightly estimates while the month
        # is still open (adjustment runs never drive the dashboard). The returned
        # ``payout_kind`` lets the UI label an estimate honestly.
        live = PayoutRun.objects.filter(
            target_period=period, status__in=live_statuses,
            kind__in=[PayoutRun.FINAL, PayoutRun.ESTIMATE],
        ).values_list('id', 'kind')
        final_ids = [rid for rid, kind in live if kind == PayoutRun.FINAL]
        estimate_ids = [rid for rid, kind in live if kind == PayoutRun.ESTIMATE]
        run_ids = final_ids or estimate_ids
        if not run_ids:
            return empty
        payout_kind = PayoutRun.FINAL if final_ids else PayoutRun.ESTIMATE

        sees_all = (
            user is None
            or getattr(user, 'is_superuser', False)
            or highest_level(user, 'final_payout') in ('full', 'view_all')
        )
        user_entity_id = getattr(user, 'entity_id', None) if user is not None else None

        info = {'available': True, 'estimated_payout': None, 'payout_kind': payout_kind,
                'kpi_lines': {}, 'child_payouts': {}}
        if entity is not None and (sees_all or entity.pk == user_entity_id):
            own = list(Payout.objects.filter(
                run_id__in=run_ids, entity=entity,
            ).prefetch_related('line_items'))
            if own:
                total = sum((p.total_payout for p in own), Decimal('0.00'))
                info['estimated_payout'] = str(total)
                for payout in own:
                    for line in payout.line_items.all():
                        info['kpi_lines'][line.kpi_code] = {
                            'multiplier': str(line.applied_multiplier),
                            'weight_pct': str(line.weightage),
                        }
        if child_ids and sees_all:
            rows = Payout.objects.filter(
                run_id__in=run_ids, entity_id__in=child_ids,
            ).values('entity_id').annotate(total=Sum('total_payout'))
            info['child_payouts'] = {r['entity_id']: str(r['total']) for r in rows}
        return info


class PayoutCycleService:
    """The month-close process around the payout engine: one ``PayoutCycle`` per period owns
    readiness → finalize (freeze achievements) → compute (final runs off the frozen numbers).
    Review, cycle-level approval and disbursement land in P3; adjustments in P5."""

    # ── cycle open / lookup ──────────────────────────────────────────────────
    @staticmethod
    def open_cycle(period, actor=None) -> PayoutCycle:
        """The single live cycle for a period (created on first touch)."""
        cycle, created = PayoutCycle.objects.get_or_create(target_period=period)
        if created:
            AuditService.log('create', 'incentives.PayoutCycle', cycle.pk, actor,
                             {'period': period.code})
        return cycle

    # ── readiness (§5) ───────────────────────────────────────────────────────
    @staticmethod
    def readiness(cycle: PayoutCycle) -> dict:
        """Recompute the readiness checklist, persist the snapshot, and return it.
        Deliberately thin: read-only queries over existing data, one row per check
        (status ∈ green/warning/red). A red check blocks finalize unless overridden."""
        period = cycle.target_period
        checks = [
            PayoutCycleService._check_targets_published(period),
            PayoutCycleService._check_exceptions_decided(period),
            PayoutCycleService._check_variable_pay(period),
            PayoutCycleService._check_achievements_fresh(period),
            PayoutCycleService._check_gate_data(period),
            PayoutCycleService._check_integration_batches(period),
        ]
        snapshot = {
            'is_ready': all(c['status'] != 'red' for c in checks),
            'checks': checks,
            'computed_at': timezone.now().isoformat(),
        }
        cycle.readiness = snapshot
        cycle.save(update_fields=['readiness', 'updated_at'])
        return snapshot

    @staticmethod
    def _check_targets_published(period) -> dict:
        from apps.targets.models import TargetPlan

        plans = TargetPlan.objects.filter(period=period, is_active=True)
        total = plans.count()
        if total == 0:
            return _check('targets_published', 'Targets published', 'warning', 0,
                          'No plans for this period (targets may be bulk-imported).')
        unpublished = plans.exclude(
            status__in=[TargetPlan.PUBLISHED, TargetPlan.LOCKED],
        ).count()
        if unpublished:
            return _check('targets_published', 'Targets published', 'red', unpublished,
                          f'{unpublished} of {total} plans are not published/locked.')
        return _check('targets_published', 'Targets published', 'green', 0,
                      f'All {total} plans published.')

    @staticmethod
    def _check_exceptions_decided(period) -> dict:
        pending = PayoutException.objects.filter(
            target_period=period, status=PayoutException.PENDING, is_active=True,
        ).count()
        status = 'red' if pending else 'green'
        return _check('exceptions_decided', 'Exceptions decided', status, pending,
                      f'{pending} exception(s) still pending.' if pending
                      else 'No pending exceptions.')

    @staticmethod
    def _check_variable_pay(period) -> dict:
        from apps.hierarchy.models import Node

        eligible = PayoutCycleService._eligible_entity_ids(period)

        if not eligible:
            return _check('variable_pay', 'Variable pay loaded', 'green', 0,
                          'No eligible entities for this period.')

        have = set(VariablePay.objects.filter(
            target_period=period, entity_id__in=eligible, is_active=True,
        ).values_list('entity_id', flat=True))
        missing_ids = eligible - have
        status = 'red' if missing_ids else 'green'
        if not missing_ids:
            return _check('variable_pay', 'Variable pay loaded', status, 0,
                          f'All {len(eligible)} eligible entities covered.')
        # Name the gap — "1 missing" isn't actionable, "Manoj Pillai" is.
        names = list(Node.objects.filter(pk__in=missing_ids)
                     .order_by('name').values_list('name', flat=True)[:5])
        listed = ', '.join(names) + (f' +{len(missing_ids) - len(names)} more'
                                     if len(missing_ids) > len(names) else '')
        return _check('variable_pay', 'Variable pay loaded', status, len(missing_ids),
                      f'{len(missing_ids)} of {len(eligible)} eligible entities have no '
                      f'variable pay: {listed}.')

    @staticmethod
    def _check_achievements_fresh(period) -> dict:
        from apps.achievements.models import Achievement
        from apps.kpi_engine.models import Transaction

        last_compute = Achievement.objects.filter(
            target_period=period,
        ).aggregate(m=Max('computed_at'))['m']
        if last_compute is None:
            return _check('achievements_fresh', 'Achievements fresh', 'red', 0,
                          'Achievements have never been computed for this period.')
        last_txn = Transaction.objects.filter(
            is_active=True, transaction_date__gte=period.start_date,
            transaction_date__lte=period.end_date,
        ).aggregate(m=Max('created_at'))['m']
        if last_txn is not None and last_txn > last_compute:
            return _check('achievements_fresh', 'Achievements fresh', 'warning', 0,
                          'Sales landed after the last achievement compute — recompute recommended.')
        return _check('achievements_fresh', 'Achievements fresh', 'green', 0,
                      'Achievements reflect the latest sales.')

    @staticmethod
    def _check_gate_data(period) -> dict:
        from apps.kpi_engine.models import ExternalMetric, ExternalMetricValue, KPIDefinition

        gate_kpi_ids = set(SchemeGate.objects.filter(
            scheme__is_current=True, scheme__is_active=True,
        ).values_list('kpi_id', flat=True))
        external_gates = KPIDefinition.objects.filter(
            id__in=gate_kpi_ids, kpi_type=KPIDefinition.EXTERNAL,
        )
        missing = []
        for kpi in external_gates:
            metric_code = (kpi.external_config or {}).get('metric_code')
            metric = ExternalMetric.objects.filter(code=metric_code, is_active=True).first()
            has_data = metric is not None and ExternalMetricValue.objects.filter(
                metric=metric, is_active=True,
                measured_on__gte=period.start_date, measured_on__lte=period.end_date,
            ).exists()
            if not has_data:
                missing.append(kpi.code)
        if missing:
            return _check('gate_data', 'Gate data present', 'red', len(missing),
                          f'No metric values in the period for gate KPI(s): {", ".join(missing)}.')
        return _check('gate_data', 'Gate data present', 'green', 0,
                      'All external gate KPIs have data (or none are used).')

    @staticmethod
    def _check_integration_batches(period) -> dict:
        from apps.kpi_engine.models import IntegrationBatch

        unreconciled = IntegrationBatch.objects.filter(
            created_at__date__gte=period.start_date,
            status__in=[IntegrationBatch.PARTIAL, IntegrationBatch.REJECTED],
        ).count()
        status = 'red' if unreconciled else 'green'
        return _check('integration_batches', 'Integration batches reconciled', status,
                      unreconciled,
                      f'{unreconciled} batch(es) partial/rejected since the period start.'
                      if unreconciled else 'All integration batches accepted.')

    # ── finalize (freeze achievements) ───────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def finalize(cycle: PayoutCycle, actor=None, override: bool = False,
                 override_reason: str = '', as_of=None) -> PayoutCycle:
        """Freeze the period's achievements: run one last achievement compute, flip its rows
        to non-provisional, stamp ``finalized_at``. Red readiness checks require an explicit,
        audited override (same pattern as the target plan's force-close)."""
        from apps.achievements.models import Achievement
        from apps.achievements.services import AchievementService
        from apps.targets.models import TargetPeriod
        from apps.targets.services import TargetService

        if cycle.status not in (PayoutCycle.OPEN, PayoutCycle.FINALIZING):
            raise BusinessError(
                f'Only an open cycle can be finalized (status: {cycle.status}).'
            )
        snapshot = PayoutCycleService.readiness(cycle)
        if not snapshot['is_ready']:
            if not override:
                red = [c['key'] for c in snapshot['checks'] if c['status'] == 'red']
                raise BusinessError(
                    'Readiness checks are not green: ' + ', '.join(red)
                    + '. Resolve them or finalize with an audited override.'
                )
            if not (override_reason or '').strip():
                raise BusinessError('An override reason is required to finalize with red checks.')
            cycle.readiness_overridden = True
            cycle.override_reason = override_reason
            AuditService.log('readiness_override', 'incentives.PayoutCycle', cycle.pk, actor,
                             {'reason': override_reason,
                              'red_checks': [c['key'] for c in snapshot['checks']
                                             if c['status'] == 'red']})

        cycle.status = PayoutCycle.FINALIZING
        cycle.save(update_fields=['status', 'readiness_overridden', 'override_reason', 'updated_at'])

        period = cycle.target_period
        result = AchievementService.compute_period(period.id, triggered_by=actor, as_of=as_of)
        Achievement.objects.filter(target_period=period).update(is_provisional=False)
        # Freezing achievements freezes targets too: the period locks (and its
        # allocations with it) so final payouts compute against an immutable base.
        TargetService.advance_period(period, TargetPeriod.LOCKED, actor=actor,
                                     source=f'payout cycle {cycle.pk} finalized')

        cycle.finalized_at = timezone.now()
        cycle.finalized_by = actor
        cycle.achievement_computation_id = result['computation_id']
        cycle.status = PayoutCycle.COMPUTING
        cycle.save(update_fields=['finalized_at', 'finalized_by', 'achievement_computation_id',
                                  'status', 'updated_at'])
        AuditService.log('finalize', 'incentives.PayoutCycle', cycle.pk, actor,
                         {'period': period.code, 'computation_id': result['computation_id'],
                          'overridden': cycle.readiness_overridden})
        return cycle

    # ── compute (final runs off frozen numbers) ──────────────────────────────
    @staticmethod
    def compute(cycle: PayoutCycle, actor=None) -> dict:
        """Compute a final run for every active scheme of the period, off the frozen
        achievements. Requires the cycle to be finalized (that is what makes a run *final*,
        not an estimate). Leaves the cycle in ``under_review`` for the P3 review board."""
        if cycle.finalized_at is None:
            raise BusinessError(
                'Finalize the cycle (freeze achievements) before computing final payouts.'
            )
        if cycle.status not in (PayoutCycle.COMPUTING, PayoutCycle.UNDER_REVIEW):
            raise BusinessError(
                f'The cycle is {cycle.status}; final runs compute from the computing state.'
            )
        period = cycle.target_period
        schemes = PayoutCycleService._matching_schemes(period)
        run_ids, total = [], Decimal('0.00')
        for scheme in schemes:
            run = PayoutService.start_run(
                scheme.pk, period.pk, actor=actor, kind=PayoutRun.FINAL, cycle=cycle,
            )
            result = PayoutService.compute_run(run.pk, triggered_by=actor)
            total += Decimal(result['total_payout'])
            run_ids.append(run.pk)
        cycle.total_payout = total
        cycle.status = PayoutCycle.UNDER_REVIEW
        cycle.save(update_fields=['total_payout', 'status', 'updated_at'])
        AuditService.log('compute', 'incentives.PayoutCycle', cycle.pk, actor,
                         {'runs': run_ids, 'total_payout': str(total)})
        return {'cycle_id': cycle.pk, 'run_ids': run_ids, 'total_payout': str(total)}

    # ── per-payee hold / release (pre-disbursement) ──────────────────────────
    @staticmethod
    def can_hold(payout: Payout) -> bool:
        """Whether ``hold_payout`` would be accepted now — the single source of truth the
        UI reads so it never offers a hold the API will refuse. Mirrors the guards below."""
        cycle = payout.run.cycle
        return (cycle is not None and cycle.status == PayoutCycle.UNDER_REVIEW
                and payout.run.kind == PayoutRun.FINAL
                and payout.hold_status != Payout.HOLD_HELD)

    @staticmethod
    def can_release(payout: Payout) -> bool:
        """Whether ``release_payout`` would be accepted now (mirrors the guards below)."""
        cycle = payout.run.cycle
        return (cycle is not None and cycle.status == PayoutCycle.UNDER_REVIEW
                and payout.hold_status == Payout.HOLD_HELD)

    @staticmethod
    def hold_payout(payout: Payout, actor=None, reason: str = '') -> Payout:
        """Hold one payee during review — excluded from the register, dispute resolved
        without blocking the payroll cutoff for everyone else."""
        if not (reason or '').strip():
            raise BusinessError('A reason is required to hold a payout.')
        cycle = payout.run.cycle
        if cycle is None or cycle.status != PayoutCycle.UNDER_REVIEW:
            raise BusinessError('Payouts can only be held while the cycle is under review.')
        if payout.run.kind != PayoutRun.FINAL:
            raise BusinessError('Only a final-run payout can be held.')
        payout.hold_status = Payout.HOLD_HELD
        payout.hold_reason = reason
        payout.save(update_fields=['hold_status', 'hold_reason', 'updated_at'])
        AuditService.log('hold', 'incentives.Payout', payout.pk, actor,
                         {'entity_id': payout.entity_id, 'reason': reason})
        return payout

    @staticmethod
    def release_payout(payout: Payout, actor=None) -> Payout:
        """Release a held payout before the register is cut, so it pays normally this cycle."""
        if payout.hold_status != Payout.HOLD_HELD:
            raise BusinessError('This payout is not held.')
        cycle = payout.run.cycle
        if cycle is None or cycle.status != PayoutCycle.UNDER_REVIEW:
            raise BusinessError(
                'A held payout can only be released before disbursement; after that it rides '
                'the next cycle as an adjustment.'
            )
        payout.hold_status = Payout.HOLD_RELEASED
        payout.save(update_fields=['hold_status', 'updated_at'])
        AuditService.log('release', 'incentives.Payout', payout.pk, actor,
                         {'entity_id': payout.entity_id})
        return payout

    # ── cycle maker-checker + disbursement ───────────────────────────────────
    @staticmethod
    def submit_cycle(cycle: PayoutCycle, actor=None) -> PayoutCycle:
        """Maker declares the reviewed cycle ready for a checker's approval."""
        if cycle.status != PayoutCycle.UNDER_REVIEW:
            raise BusinessError(f'Only a cycle under review can be submitted (status: {cycle.status}).')
        cycle.submitted_by = actor
        cycle.submitted_at = timezone.now()
        cycle.save(update_fields=['submitted_by', 'submitted_at', 'updated_at'])
        AuditService.log('submit', 'incentives.PayoutCycle', cycle.pk, actor, {})
        return cycle

    @staticmethod
    @transaction.atomic
    def approve_cycle(cycle: PayoutCycle, actor=None) -> PayoutCycle:
        """Checker (≠ submitter) approves the cycle; its final runs move to approved as one.
        Cycle-level approval is the governing maker-checker — the per-run approval endpoints
        stay only for single-scheme reruns."""
        if cycle.status != PayoutCycle.UNDER_REVIEW:
            raise BusinessError(f'Only a cycle under review can be approved (status: {cycle.status}).')
        if cycle.submitted_by_id is None:
            raise BusinessError('Submit the cycle for approval before it can be approved.')
        if actor is not None and cycle.submitted_by_id == actor.pk:
            raise BusinessError('A cycle cannot be approved by its submitter (maker-checker).')
        now = timezone.now()
        for run in cycle.runs.filter(
            kind__in=[PayoutRun.FINAL, PayoutRun.ADJUSTMENT], status=PayoutRun.COMPUTED,
        ):
            run.submitted_by = cycle.submitted_by
            run.submitted_at = cycle.submitted_at
            run.approved_by = actor
            run.approved_at = now
            run.status = PayoutRun.APPROVED
            run.save(update_fields=['submitted_by', 'submitted_at', 'approved_by',
                                    'approved_at', 'status', 'updated_at'])
            AuditService.log('approve', 'incentives.PayoutRun', run.pk, actor,
                             {'via': 'cycle', 'cycle_id': cycle.pk})
        cycle.approved_by = actor
        cycle.approved_at = now
        cycle.status = PayoutCycle.APPROVED
        cycle.save(update_fields=['approved_by', 'approved_at', 'status', 'updated_at'])
        AuditService.log('approve', 'incentives.PayoutCycle', cycle.pk, actor, {})
        return cycle

    @staticmethod
    def reject_cycle(cycle: PayoutCycle, actor=None, reason: str = '') -> PayoutCycle:
        """Send a submitted cycle back into review (clears the maker's submission)."""
        if cycle.status != PayoutCycle.UNDER_REVIEW:
            raise BusinessError(f'Only a cycle under review can be rejected (status: {cycle.status}).')
        cycle.submitted_by = None
        cycle.submitted_at = None
        cycle.save(update_fields=['submitted_by', 'submitted_at', 'updated_at'])
        AuditService.log('reject', 'incentives.PayoutCycle', cycle.pk, actor, {'reason': reason})
        return cycle

    @staticmethod
    @transaction.atomic
    def disburse_cycle(cycle: PayoutCycle, actor=None, payment_ref: str = '',
                       register_ref: str = '') -> PayoutCycle:
        """Mark the approved cycle disbursed: its final runs go to paid, the register total is
        recomputed excluding held payouts, and the payment reference is recorded."""
        if cycle.status != PayoutCycle.APPROVED:
            raise BusinessError(f'Only an approved cycle can be disbursed (status: {cycle.status}).')
        now = timezone.now()
        for run in cycle.runs.filter(
            kind__in=[PayoutRun.FINAL, PayoutRun.ADJUSTMENT], status=PayoutRun.APPROVED,
        ):
            run.status = PayoutRun.PAID
            run.paid_at = now
            run.payment_ref = payment_ref
            run.save(update_fields=['status', 'paid_at', 'payment_ref', 'updated_at'])
            AuditService.log('mark_paid', 'incentives.PayoutRun', run.pk, actor,
                             {'via': 'cycle', 'payment_ref': payment_ref})
        cycle.total_payout = PayoutCycleService._cycle_payable_total(cycle)
        cycle.disbursed_by = actor
        cycle.disbursed_at = now
        cycle.register_ref = register_ref or payment_ref
        cycle.status = PayoutCycle.DISBURSED
        cycle.save(update_fields=['total_payout', 'disbursed_by', 'disbursed_at',
                                  'register_ref', 'status', 'updated_at'])
        AuditService.log('disburse', 'incentives.PayoutCycle', cycle.pk, actor,
                         {'payment_ref': payment_ref, 'total_payout': str(cycle.total_payout)})
        return cycle

    @staticmethod
    def close_cycle(cycle: PayoutCycle, actor=None) -> PayoutCycle:
        """Archive a disbursed cycle. After close, numbers only change via adjustment runs (P5)."""
        from apps.targets.models import TargetPeriod
        from apps.targets.services import TargetService

        if cycle.status != PayoutCycle.DISBURSED:
            raise BusinessError(f'Only a disbursed cycle can be closed (status: {cycle.status}).')
        cycle.status = PayoutCycle.CLOSED
        cycle.save(update_fields=['status', 'updated_at'])
        TargetService.advance_period(cycle.target_period, TargetPeriod.CLOSED, actor=actor,
                                     source=f'payout cycle {cycle.pk} closed')
        AuditService.log('close', 'incentives.PayoutCycle', cycle.pk, actor, {})
        return cycle

    # ── adjustments (late data after payday) ─────────────────────────────────
    @staticmethod
    @transaction.atomic
    def create_adjustment(reference_run: PayoutRun, target_cycle: PayoutCycle, actor=None) -> dict:
        """Raise an adjustment run against a paid, closed-cycle run. It recomputes the scheme
        off the reference month's restated achievements and pays the per-payee delta in the
        current (still-open) cycle. The paid run is never mutated."""
        if reference_run.kind != PayoutRun.FINAL or reference_run.status != PayoutRun.PAID:
            raise BusinessError('An adjustment must reference a paid final run.')
        ref_cycle = reference_run.cycle
        if ref_cycle is None or ref_cycle.status != PayoutCycle.CLOSED:
            raise BusinessError(
                'The referenced run’s cycle must be closed before it can be adjusted.'
            )
        if target_cycle.status not in (PayoutCycle.OPEN, PayoutCycle.COMPUTING, PayoutCycle.UNDER_REVIEW):
            raise BusinessError(
                'Adjustments ride an open cycle — they cannot be added after disbursement.'
            )
        # The restatement must be real: an achievement compute for the reference period more
        # recent than the one the reference cycle was frozen against. Exception: a payee left
        # HELD at disbursement was never paid — their amount rides this adjustment even when
        # nothing was restated.
        latest_compute = ComputationLog.objects.filter(
            computation_type='achievement', period_id=reference_run.target_period_id,
        ).order_by('-timestamp', '-id').values_list('id', flat=True).first()
        has_held = reference_run.payouts.filter(hold_status=Payout.HOLD_HELD).exists()
        if (latest_compute is None or latest_compute == ref_cycle.achievement_computation_id) \
                and not has_held:
            raise BusinessError(
                'No achievement restatement since the reference cycle was finalized. Recompute '
                'achievements for that period after the new data lands, then raise the adjustment.'
            )

        # Supersede any prior live adjustment for this scheme in the target cycle's period.
        prior = PayoutRun.objects.filter(
            scheme=reference_run.scheme, target_period=target_cycle.target_period,
            kind=PayoutRun.ADJUSTMENT, status__in=PayoutRun.LIVE_STATUSES,
        ).select_for_update()
        for r in prior:
            r.status = PayoutRun.SUPERSEDED
            r.save(update_fields=['status', 'updated_at'])

        run = PayoutRun.objects.create(
            scheme=reference_run.scheme, target_period=target_cycle.target_period,
            kind=PayoutRun.ADJUSTMENT, cycle=target_cycle, reference_run=reference_run,
            status=PayoutRun.COMPUTING, triggered_by=actor,
        )
        result = PayoutService.compute_adjustment_run(run.pk, triggered_by=actor)
        AuditService.log('adjust', 'incentives.PayoutRun', run.pk, actor,
                         {'reference_run': reference_run.pk,
                          'reference_period': reference_run.target_period.code,
                          'net_delta': result['net_delta']})
        return {'run_id': run.pk, **result}

    # ── nightly estimates ────────────────────────────────────────────────────
    @staticmethod
    def compute_estimates(cycle: PayoutCycle, actor=None) -> dict:
        """Recompute the nightly estimate run for every active scheme of an open cycle's
        period. Estimates auto-supersede the prior night's and can never be submitted."""
        if cycle.status != PayoutCycle.OPEN:
            return {'cycle_id': cycle.pk, 'run_ids': [], 'skipped': f'cycle {cycle.status}'}
        period = cycle.target_period
        run_ids = []
        for scheme in PayoutCycleService._matching_schemes(period):
            run = PayoutService.start_run(
                scheme.pk, period.pk, actor=actor, kind=PayoutRun.ESTIMATE, cycle=cycle,
            )
            PayoutService.compute_run(run.pk, triggered_by=actor)
            run_ids.append(run.pk)
        return {'cycle_id': cycle.pk, 'run_ids': run_ids}

    # ── shared helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _matching_schemes(period):
        """Active current schemes whose payout frequency matches the period type."""
        frequency = (IncentiveScheme.ANNUAL if period.period_type == period.ANNUAL
                     else IncentiveScheme.MONTHLY)
        return list(IncentiveScheme.objects.filter(
            is_current=True, is_active=True, payout_frequency=frequency,
        ).select_related('target_entity_type'))

    @staticmethod
    def _eligible_entity_ids(period) -> set:
        """Union of entities eligible under any scheme matching the period type."""
        from apps.hierarchy.models import Node

        ids: set = set()
        for scheme in PayoutCycleService._matching_schemes(period):
            qs = Node.objects.filter(
                entity_type__code=scheme.target_entity_type.code,
                is_current=True, is_active=True, status='active',
            )
            if scheme.channel_id:
                qs = qs.filter(channel_id=scheme.channel_id)
            ids.update(qs.values_list('id', flat=True))
        return ids

    @staticmethod
    def _final_payouts(cycle):
        """All final-run payouts of the cycle (held included), newest runs only."""
        return Payout.objects.filter(
            run__cycle=cycle, run__kind=PayoutRun.FINAL,
        ).exclude(run__status__in=[PayoutRun.SUPERSEDED, PayoutRun.FAILED])

    @staticmethod
    def _payable_payouts(cycle):
        """Final-run payouts that actually pay this cycle — held ones are excluded."""
        return PayoutCycleService._final_payouts(cycle).exclude(hold_status=Payout.HOLD_HELD)

    @staticmethod
    def _adjustment_payouts(cycle):
        """Adjustment-run rows riding this cycle (arrears/recoveries for prior closed months)."""
        return Payout.objects.filter(
            run__cycle=cycle, run__kind=PayoutRun.ADJUSTMENT,
        ).exclude(run__status__in=[PayoutRun.SUPERSEDED, PayoutRun.FAILED])

    @staticmethod
    def _cycle_payable_total(cycle) -> Decimal:
        """What actually disburses this cycle: payable final payouts + adjustment deltas."""
        finals = PayoutCycleService._payable_payouts(cycle).aggregate(
            t=Sum('total_payout'))['t'] or Decimal('0.00')
        adjustments = PayoutCycleService._adjustment_payouts(cycle).aggregate(
            t=Sum('adjustment_amount'))['t'] or Decimal('0.00')
        return finals + adjustments

    # ── review board (§7) ────────────────────────────────────────────────────
    @staticmethod
    def review(cycle: PayoutCycle) -> dict:
        """The review board payload: cross-scheme stat strip, variance vs the prior cycle,
        multiplier distribution, biggest movers, and capped/gated/held/exception drill lists."""
        payouts = list(
            PayoutCycleService._final_payouts(cycle)
            .select_related('entity', 'entity__entity_type', 'scheme')
        )
        payable = [p for p in payouts if p.hold_status != Payout.HOLD_HELD]
        total = sum((p.total_payout for p in payable), Decimal('0.00'))

        by_scheme: dict[str, dict] = {}
        for p in payable:
            row = by_scheme.setdefault(p.scheme.code, {
                'scheme_code': p.scheme.code, 'scheme_name': p.scheme.name,
                'total': Decimal('0.00'), 'payees': 0,
            })
            row['total'] += p.total_payout
            row['payees'] += 1

        prior_cycle = PayoutCycleService._prior_cycle(cycle)
        variance = None
        prior_by_entity: dict[int, Decimal] = {}
        if prior_cycle is not None:
            prior_payable = list(PayoutCycleService._payable_payouts(prior_cycle))
            prior_total = sum((p.total_payout for p in prior_payable), Decimal('0.00'))
            for p in prior_payable:
                prior_by_entity[p.entity_id] = prior_by_entity.get(p.entity_id, Decimal('0.00')) + p.total_payout
            delta = total - prior_total
            variance = {
                'prior_period_code': prior_cycle.target_period.code,
                'prior_total': str(prior_total),
                'delta': str(delta),
                'delta_pct': str(_ratio_pct(delta, prior_total)),
            }

        adjustments = list(
            PayoutCycleService._adjustment_payouts(cycle)
            .select_related('entity', 'run__reference_run__target_period')
        )
        adjustments_net = sum((p.adjustment_amount for p in adjustments), Decimal('0.00'))

        return {
            'cycle_id': cycle.pk,
            'period_code': cycle.target_period.code,
            'status': cycle.status,
            'stats': {
                'total_payout': str(total),
                'payees': len(payable),
                'held': sum(1 for p in payouts if p.hold_status == Payout.HOLD_HELD),
                'capped': sum(1 for p in payable if p.capped),
                'gated': sum(1 for p in payable if p.gatekeeper_status == Payout.GK_FAILED),
                'exceptions': sum(1 for p in payable if p.exception_id is not None),
                'adjustments': len(adjustments),
                'adjustments_net': str(adjustments_net),
                'grand_total': str(total + adjustments_net),
            },
            'adjustments': [
                {'payout_id': p.pk, 'entity_code': p.entity.code, 'entity_name': p.entity.name,
                 'adjustment_amount': str(p.adjustment_amount),
                 'adjustment_for': (p.run.reference_run.target_period.code
                                    if p.run.reference_run_id else None)}
                for p in sorted(adjustments, key=lambda x: x.adjustment_amount)
            ],
            'by_scheme': [
                {**r, 'total': str(r['total'])}
                for r in sorted(by_scheme.values(), key=lambda r: r['scheme_code'])
            ],
            'variance': variance,
            'multiplier_distribution': PayoutCycleService._distribution(payable),
            'movers': PayoutCycleService._movers(payable, prior_by_entity),
            'outliers': PayoutCycleService._outliers(payouts),
        }

    @staticmethod
    def _prior_cycle(cycle):
        from apps.targets.models import TargetPeriod

        period = cycle.target_period
        prior_period = TargetPeriod.objects.filter(
            period_type=period.period_type, start_date__lt=period.start_date, is_active=True,
        ).order_by('-start_date').first()
        return getattr(prior_period, 'payout_cycle', None) if prior_period else None

    _DIST_BUCKETS = [
        ('<0.5', None, Decimal('0.5')),
        ('0.5–0.8', Decimal('0.5'), Decimal('0.8')),
        ('0.8–1.0', Decimal('0.8'), Decimal('1.0')),
        ('1.0–1.2', Decimal('1.0'), Decimal('1.2')),
        ('≥1.2', Decimal('1.2'), None),
    ]

    @staticmethod
    def _distribution(payouts) -> list[dict]:
        out = []
        for label, lo, hi in PayoutCycleService._DIST_BUCKETS:
            count = sum(
                1 for p in payouts
                if (lo is None or p.total_multiplier >= lo) and (hi is None or p.total_multiplier < hi)
            )
            out.append({'bucket': label, 'count': count})
        return out

    @staticmethod
    def _movers(payouts, prior_by_entity: dict) -> dict:
        deltas = []
        for p in payouts:
            prior = prior_by_entity.get(p.entity_id)
            if prior is None:
                continue
            deltas.append({
                'entity_code': p.entity.code, 'entity_name': p.entity.name,
                'current': str(p.total_payout), 'prior': str(prior),
                'delta': str(p.total_payout - prior),
                '_d': p.total_payout - prior,
            })
        deltas.sort(key=lambda r: r['_d'], reverse=True)
        gainers = [{k: v for k, v in r.items() if k != '_d'} for r in deltas[:5] if r['_d'] > 0]
        losers = [{k: v for k, v in r.items() if k != '_d'}
                  for r in sorted(deltas, key=lambda r: r['_d'])[:5] if r['_d'] < 0]
        return {'gainers': gainers, 'losers': losers}

    @staticmethod
    def _outliers(payouts) -> dict:
        def rows(pred):
            return [
                {'payout_id': p.pk, 'entity_code': p.entity.code, 'entity_name': p.entity.name,
                 'total_payout': str(p.total_payout)}
                for p in payouts if pred(p)
            ]
        return {
            'capped': rows(lambda p: p.capped and p.hold_status != Payout.HOLD_HELD),
            'gated': rows(lambda p: p.gatekeeper_status == Payout.GK_FAILED
                          and p.hold_status != Payout.HOLD_HELD),
            'held': rows(lambda p: p.hold_status == Payout.HOLD_HELD),
            'exceptions': rows(lambda p: p.exception_id is not None
                               and p.hold_status != Payout.HOLD_HELD),
        }

    # ── disbursement register + statement (§6) ───────────────────────────────
    @staticmethod
    def register(cycle: PayoutCycle, *, bank_attribute_keys=None,
                 include_held: bool = False) -> dict:
        """The disbursement register finance uploads to payroll/bank. Held payouts are
        excluded (they ride the next cycle); the total reconciles to the payable payouts to
        the paisa. Bank columns are pulled from the entity's configured attribute keys."""
        bank_attribute_keys = list(bank_attribute_keys or [])
        finals = (PayoutCycleService._final_payouts(cycle) if include_held
                  else PayoutCycleService._payable_payouts(cycle))
        finals = finals.select_related('entity', 'entity__entity_type', 'scheme', 'run')
        adjustments = PayoutCycleService._adjustment_payouts(cycle).select_related(
            'entity', 'entity__entity_type', 'scheme', 'run', 'run__reference_run__target_period',
        )
        # (payout, kind, payable_amount) — final rows pay their total, adjustment rows pay the delta.
        entries = [(p, 'final', p.total_payout) for p in finals]
        entries += [(p, 'adjustment', p.adjustment_amount) for p in adjustments]
        entries.sort(key=lambda e: (e[1], e[0].entity.path))

        rows, total = [], Decimal('0.00')
        for p, kind, payable in entries:
            attrs = p.entity.attributes or {}
            ref_period = (p.run.reference_run.target_period.code
                          if kind == 'adjustment' and p.run.reference_run_id else '')
            row = {
                'entity_code': p.entity.code,
                'entity_name': p.entity.name,
                'entity_type': p.entity.entity_type.code if p.entity.entity_type_id else None,
                'scheme_code': p.scheme.code,
                'kind': kind,
                'adjustment_for': ref_period,
                'eligible_vp': str(p.eligible_vp),
                'gross_payout': str(p.gross_payout),
                'total_payout': str(payable),
                'gatekeeper_status': p.gatekeeper_status,
                'hold_status': p.hold_status,
                'run_status': p.run.status,
                'payment_ref': p.run.payment_ref,
            }
            for key in bank_attribute_keys:
                row[key] = attrs.get(key, '')
            rows.append(row)
            total += payable

        return {
            'cycle_id': cycle.pk,
            'period_code': cycle.target_period.code,
            'status': cycle.status,
            'register_ref': cycle.register_ref,
            'bank_attribute_keys': bank_attribute_keys,
            'rows': rows,
            'total_payout': str(total),
            'payee_count': len(rows),
            'held_count': PayoutCycleService._final_payouts(cycle).filter(
                hold_status=Payout.HOLD_HELD).count(),
        }

    @staticmethod
    def register_csv(cycle: PayoutCycle, *, bank_attribute_keys=None) -> str:
        data = PayoutCycleService.register(cycle, bank_attribute_keys=bank_attribute_keys)
        base_cols = ['entity_code', 'entity_name', 'entity_type', 'scheme_code', 'kind',
                     'adjustment_for', 'eligible_vp', 'gross_payout', 'total_payout',
                     'gatekeeper_status', 'payment_ref']
        columns = base_cols + data['bank_attribute_keys']
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in data['rows']:
            writer.writerow(row)
        writer.writerow({'entity_code': 'TOTAL', 'total_payout': data['total_payout']})
        return buf.getvalue()


def _ratio_pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if not denominator:
        return Decimal('0.00')
    return (numerator / denominator * Decimal('100')).quantize(Decimal('0.01'))


def _check(key: str, label: str, status: str, count: int, detail: str) -> dict:
    return {'key': key, 'label': label, 'status': status, 'count': count, 'detail': detail}
