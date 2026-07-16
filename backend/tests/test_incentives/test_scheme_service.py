"""SchemeService — config validation (T10) and versioning behavior."""
from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.incentives.models import IncentiveScheme, MultiplierTier, SchemeKPI
from apps.incentives.services import SchemeService

D = Decimal

GRID = [
    {'min_achievement_pct': D('0'), 'max_achievement_pct': D('80'), 'multiplier': D('0')},
    {'min_achievement_pct': D('80'), 'max_achievement_pct': D('100'), 'multiplier': D('0.8')},
    {'min_achievement_pct': D('100'), 'max_achievement_pct': None, 'multiplier': D('1.2')},
]


def _payload(ase_type, kpis, **overrides):
    data = {
        'name': 'Field Force Monthly',
        'code': 'FF_MONTHLY',
        'description': '',
        'target_entity_type': ase_type,
        'channel': None,
        'vp_basis_pct': D('100.00'),
        'overall_cap_pct': None,
        'gates': [],
        'gatekeeper_action': 'zero_payout',
        'effective_from': date.today(),
        'kpis': [
            {'kpi': kpis['PRIMARY'], 'incentive_category': 'sales',
             'weightage': D('60.00'), 'tiers': [dict(t) for t in GRID]},
            {'kpi': kpis['ECO'], 'incentive_category': 'execution',
             'weightage': D('40.00'), 'tiers': [dict(t) for t in GRID]},
        ],
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestValidation:
    def test_valid_payload_creates_scheme(self, ase_type, kpis):
        scheme = SchemeService.create(_payload(ase_type, kpis))
        assert scheme.version == 1
        assert scheme.kpis.count() == 2
        assert MultiplierTier.objects.filter(scheme_kpi__scheme=scheme).count() == 6

    def test_t10_weightage_must_sum_100(self, ase_type, kpis):
        payload = _payload(ase_type, kpis)
        payload['kpis'][0]['weightage'] = D('59.99')
        with pytest.raises(BusinessError, match='sum to exactly 100'):
            SchemeService.create(payload)

    def test_t10_tier_gap_rejected(self, ase_type, kpis):
        payload = _payload(ase_type, kpis)
        payload['kpis'][0]['tiers'] = [
            {'min_achievement_pct': D('0'), 'max_achievement_pct': D('80'), 'multiplier': D('0')},
            {'min_achievement_pct': D('90'), 'max_achievement_pct': None, 'multiplier': D('1')},
        ]
        with pytest.raises(BusinessError, match='contiguous'):
            SchemeService.create(payload)

    def test_t10_tier_overlap_rejected(self, ase_type, kpis):
        payload = _payload(ase_type, kpis)
        payload['kpis'][0]['tiers'] = [
            {'min_achievement_pct': D('0'), 'max_achievement_pct': D('80'), 'multiplier': D('0')},
            {'min_achievement_pct': D('70'), 'max_achievement_pct': None, 'multiplier': D('1')},
        ]
        with pytest.raises(BusinessError, match='contiguous'):
            SchemeService.create(payload)

    def test_duplicate_kpi_rejected(self, ase_type, kpis):
        payload = _payload(ase_type, kpis)
        payload['kpis'][1]['kpi'] = kpis['PRIMARY']
        with pytest.raises(BusinessError, match='more than once'):
            SchemeService.create(payload)

    def test_gate_requires_positive_threshold(self, ase_type, kpis):
        payload = _payload(ase_type, kpis, gates=[{'kpi': kpis['MSL'], 'threshold_pct': D('0')}])
        with pytest.raises(BusinessError, match='threshold'):
            SchemeService.create(payload)

    def test_duplicate_gate_kpi_rejected(self, ase_type, kpis):
        payload = _payload(ase_type, kpis, gates=[
            {'kpi': kpis['MSL'], 'threshold_pct': D('80')},
            {'kpi': kpis['MSL'], 'threshold_pct': D('90')},
        ])
        with pytest.raises(BusinessError, match='more than once'):
            SchemeService.create(payload)

    def test_gates_saved_and_versioned(self, ase_type, kpis):
        payload = _payload(ase_type, kpis, gates=[
            {'kpi': kpis['MSL'], 'operator': 'gte', 'threshold_pct': D('80')},
        ])
        scheme = SchemeService.create(payload)
        assert scheme.gates.count() == 1
        old_pk = scheme.pk
        # New version re-creates gates on the new row (update mutates the instance in place).
        scheme2 = SchemeService.update(scheme, _payload(ase_type, kpis, gates=[
            {'kpi': kpis['MSL'], 'threshold_pct': D('85')},
            {'kpi': kpis['ECO'], 'threshold_pct': D('75')},
        ]))
        assert scheme2.gates.count() == 2
        assert IncentiveScheme.objects.get(pk=old_pk).gates.count() == 1

    def test_non_eligible_entity_type_rejected(self, kpis, db):
        from apps.hierarchy.models import NodeType
        partner = NodeType.objects.create(
            name='Retailer', code='RET', level_order=5, incentive_eligible=False,
            effective_from=date.today(),
        )
        with pytest.raises(BusinessError, match='not incentive-eligible'):
            SchemeService.create(_payload(partner, kpis))

    def test_duplicate_code_rejected(self, ase_type, kpis):
        SchemeService.create(_payload(ase_type, kpis))
        with pytest.raises(BusinessError, match='already exists'):
            SchemeService.create(_payload(ase_type, kpis))

    def test_vp_basis_bounds(self, ase_type, kpis):
        with pytest.raises(BusinessError, match='vp_basis_pct'):
            SchemeService.create(_payload(ase_type, kpis, vp_basis_pct=D('0')))
        with pytest.raises(BusinessError, match='vp_basis_pct'):
            SchemeService.create(_payload(ase_type, kpis, vp_basis_pct=D('101')))


@pytest.mark.django_db
class TestVersioning:
    def test_update_creates_new_version_with_children(self, ase_type, kpis):
        scheme = SchemeService.create(_payload(ase_type, kpis))
        old_pk = scheme.pk

        new_payload = _payload(ase_type, kpis)
        new_payload['kpis'][0]['weightage'] = D('70.00')
        new_payload['kpis'][1]['weightage'] = D('30.00')
        scheme = SchemeService.update(scheme, new_payload)

        assert scheme.pk != old_pk
        assert scheme.version == 2
        assert scheme.is_current is True
        old = IncentiveScheme.objects.get(pk=old_pk)
        assert old.is_current is False
        assert old.effective_to is not None
        # Children on both versions, independent
        assert SchemeKPI.objects.filter(scheme=old).count() == 2
        assert SchemeKPI.objects.filter(scheme=scheme).count() == 2
        assert scheme.kpis.get(kpi=kpis['PRIMARY']).weightage == D('70.00')
        assert old.kpis.get(kpi=kpis['PRIMARY']).weightage == D('60.00')

    def test_code_change_rejected_on_update(self, ase_type, kpis):
        scheme = SchemeService.create(_payload(ase_type, kpis))
        with pytest.raises(BusinessError, match='code cannot be changed'):
            SchemeService.update(scheme, _payload(ase_type, kpis, code='OTHER'))
