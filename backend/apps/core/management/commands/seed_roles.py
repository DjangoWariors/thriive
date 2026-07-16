from django.core.management.base import BaseCommand

from apps.accounts.models import Role
from apps.accounts.permission_catalog import ALL_RESOURCES


def _perms(**specified):
    """Base all resources at 'none', then apply any overrides."""
    base = {r: 'none' for r in ALL_RESOURCES}
    base.update(specified)
    return base


ROLES_SEED = [
    {
        'code': 'admin',
        'name': 'Administrator',
        'description': 'Full system access. All permissions on all resources.',
        'is_system_role': True,
        'permissions': {r: 'full' for r in ALL_RESOURCES},
    },
    {
        'code': 'national_head',
        'name': 'National Sales Head',
        'description': 'National-level read-all visibility. Full exception approval and workflow control.',
        'is_system_role': True,
        'permissions': _perms(
            dashboard='view_all',
            kpi_definitions='view_all',
            target_management='view_all',
            achievement_view='view_all',
            achievement_compute='full',
            final_payout='view_all',
            payout_approve='full',
            exception_approve='full',
            workflow_management='full',
            report_generation='full',
            report_sales='view_all',
            report_coverage='view_all',
            report_targets='view_all',
            report_master='view_all',
            report_schedule='full',
            hierarchy_management='view_all',
            audit_logs='view_readonly',
        ),
    },
    {
        'code': 'regional_manager',
        'name': 'Regional Manager',
        'description': 'Regional-level team visibility and exception approval.',
        'is_system_role': True,
        'permissions': _perms(
            dashboard='team',
            achievement_view='team',
            target_management='team',
            exception_approve='team',
            workflow_management='team',
            report_generation='team',
            report_sales='team',
            report_coverage='team',
            report_targets='team',
            report_master='team',
        ),
    },
    {
        'code': 'area_manager',
        'name': 'Area Sales Manager',
        'description': 'Area-level team management, exception handling, and target editing.',
        'is_system_role': True,
        'permissions': _perms(
            dashboard='team',
            achievement_view='team',
            target_management='view_edit',
            exception_management='team',
            workflow_management='team',
            report_sales='team',
            report_coverage='team',
            report_targets='team',
            report_master='team',
        ),
    },
    {
        'code': 'sales_officer',
        'name': 'Sales Officer / SOM',
        'description': 'Team visibility with own payout access and exception management.',
        'is_system_role': True,
        'permissions': _perms(
            dashboard='team',
            achievement_view='team',
            target_management='view_readonly',
            final_payout='own_only',
            exception_management='own_only',
        ),
    },
    {
        'code': 'sales_exec',
        'name': 'Sales Executive / ASE',
        'description': 'Own data only. Field-force individual contributor; adjusts targets '
                       'within owned territories (change-cap governed).',
        'is_system_role': True,
        'permissions': _perms(
            dashboard='own_only',
            achievement_view='own_only',
            # Territory-scoped target participation: the review cascade assigns tasks to
            # whoever owns a review-level territory — often an executive-grade persona
            # (e.g. an MT executive owning a district). 'team' + territory scoping keeps
            # them inside their owned subtree; workflow access is their approvals inbox.
            target_management='team',
            workflow_management='team',
            final_payout='own_only',
            exception_management='own_only',
            profile='own_only',
        ),
    },
    {
        'code': 'finance',
        'name': 'Finance Analyst',
        'description': 'Full payout and audit visibility. Report generation.',
        'is_system_role': True,
        'permissions': _perms(
            final_payout='view_all',
            payout_approve='full',
            report_generation='full',
            report_payout='view_all',
            report_compliance='view_all',
            report_targets='view_all',
            report_master='view_all',
            report_schedule='full',
            audit_logs='view_all',
            audit_access='view_all',
            achievement_view='view_all',
        ),
    },
    {
        'code': 'retailer',
        'name': 'Retailer',
        'description': 'Channel partner. Sees own targets, achievements and payouts only.',
        'is_system_role': True,
        'permissions': _perms(
            dashboard='own_only',
            achievement_view='own_only',
            target_management='own_only',
            final_payout='own_only',
            product_catalog='view_readonly',
            profile='own_only',
        ),
    },
    {
        'code': 'distributor',
        'name': 'Distributor',
        'description': 'Distribution partner. Sees own targets, achievements and payouts only.',
        'is_system_role': True,
        'permissions': _perms(
            dashboard='own_only',
            achievement_view='own_only',
            target_management='own_only',
            final_payout='own_only',
            product_catalog='view_readonly',
            profile='own_only',
        ),
    },
]


class Command(BaseCommand):
    help = 'Seed the 9 standard roles with their RBAC permission matrices.'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for data in ROLES_SEED:
            role, created = Role.objects.update_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'description': data['description'],
                    'is_system_role': data['is_system_role'],
                    'permissions': data['permissions'],
                    'is_active': True,
                },
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  [+] {role.code:<20} {role.name}'))
            else:
                updated_count += 1
                self.stdout.write(f'  [~] {role.code:<20} {role.name}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. {created_count} created, {updated_count} updated. '
                f'Total: {Role.objects.count()} roles.'
            )
        )
