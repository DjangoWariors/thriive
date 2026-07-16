"""
Single source of truth for the RBAC permission catalog.
Every configurable permission *resource* is declared here exactly once,
Adding a new permission resource is a one-line change here — no frontend edit.
"""

# The full level ladder, highest → lowest. Mirrors apps.core.permissions._LEVEL_RANK.
LEVELS = ['full', 'view_all', 'view_edit', 'team', 'own_only', 'view_readonly', 'none']

LEVEL_LABELS = {
    'full': 'Full',
    'view_all': 'View all',
    'view_edit': 'View + edit',
    'team': 'Team',
    'own_only': 'Own only',
    'view_readonly': 'View (read-only)',
    'none': 'None',
}

# Data resources scope through the entity tree, so the whole ladder applies.
_DATA = LEVELS
# Approval gates and system flags are binary: you either hold them or you don't.
_GATE = ['full', 'none']
# Payout-confidential resources: NEVER grantable at team/subtree levels (RFP access
# matrix — a manager sees team achievements but not team payouts). Enforced at
# role-write time (RoleService) AND clamped at resolve time
# (core.permissions.highest_level), so even a hand-seeded 'team' grant is inert.
CONFIDENTIAL_LEVELS = ['full', 'view_all', 'own_only', 'view_readonly', 'none']
CONFIDENTIAL_RESOURCES = frozenset({'final_payout', 'report_payout'})


def _r(code: str, label: str, levels: list[str] = _DATA) -> dict:
    return {'code': code, 'label': label, 'levels': levels}


PERMISSION_CATALOG = [
    {
        'group': 'General',
        'resources': [
            _r('dashboard', 'Dashboard'),
            _r('profile', 'Profile'),
        ],
    },
    {
        'group': 'KPI & Targets',
        'resources': [
            _r('kpi_definitions', 'KPI Definitions'),
            _r('target_management', 'Target Management'),
            _r('achievement_view', 'Achievement View'),
            _r('achievement_compute', 'Achievement Compute', _GATE),
        ],
    },
    {
        'group': 'Incentives',
        'resources': [
            _r('scheme_management', 'Incentive Schemes'),
            _r('final_payout', 'Final Payout', CONFIDENTIAL_LEVELS),
            _r('payout_approve', 'Payout Approval', _GATE),
            _r('exception_management', 'Exception Management'),
            _r('exception_approve', 'Exception Approval', _GATE),
        ],
    },
    {
        'group': 'Master Data',
        'resources': [
            _r('master_data', 'Master Data'),
            _r('product_catalog', 'Product Catalog'),
            _r('invoices', 'Invoices'),
        ],
    },
    {
        'group': 'Hierarchy & Workflow',
        'resources': [
            _r('hierarchy_management', 'Hierarchy Management'),
            _r('workflow_management', 'Workflow Management'),
        ],
    },
    {
        'group': 'Administration',
        'resources': [
            _r('user_management', 'User Management'),
            _r('role_management', 'Role Management'),
            _r('system_admin', 'System Administration', _GATE),
        ],
    },
    {
        'group': 'Integrations',
        'resources': [
            _r('integration_push', 'Integration Data Push', _GATE),
            _r('integration_monitor', 'Integration Monitor', _GATE),
        ],
    },
    {
        'group': 'Reports',
        'resources': [
            _r('report_generation', 'Report Generation'),
            _r('report_sales', 'Sales Reports'),
            _r('report_coverage', 'Coverage Reports'),
            _r('report_targets', 'Target Reports'),
            _r('report_payout', 'Payout Reports', CONFIDENTIAL_LEVELS),
            _r('report_master', 'Master Data Reports'),
            _r('report_compliance', 'Compliance Reports'),
            _r('report_schedule', 'Report Scheduling'),
        ],
    },
    {
        'group': 'Audit',
        'resources': [
            _r('audit_logs', 'Audit Logs'),
            _r('audit_access', 'Access Disclosure Trail'),
        ],
    },
]

# Flat list of every resource code — the only place the resource set is enumerated.
ALL_RESOURCES = [r['code'] for group in PERMISSION_CATALOG for r in group['resources']]

# code → allowed levels, for write-time validation and the resolve-time clamp.
RESOURCE_LEVELS = {
    r['code']: r['levels'] for group in PERMISSION_CATALOG for r in group['resources']
}
