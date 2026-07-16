from django.core.management.base import BaseCommand

from apps.admin_console.models import FeatureFlag, SystemSetting

_C = SystemSetting.Category

SETTINGS_SEED = [
    # TDS (India, Budget-2026 rates) — configurable so a rate change is no-code.
    ('tds.194h.rate', _C.TDS, 2, 'number', 'TDS rate % on commission (Sec 194H)'),
    ('tds.194h.threshold', _C.TDS, 20000, 'number', 'Annual exemption threshold ₹ (194H)'),
    ('tds.194r.rate', _C.TDS, 10, 'number', 'TDS rate % on benefits/perquisites (Sec 194R)'),
    ('tds.194r.threshold', _C.TDS, 20000, 'number', 'Annual exemption threshold ₹ (194R)'),
    ('tds.no_pan_rate', _C.TDS, 20, 'number', 'Higher TDS rate % when PAN not on record'),
    # Fiscal / financial
    ('fiscal_year_start_month', _C.FINANCIAL, 4, 'number', 'Fiscal year start month (1-12)'),
    ('rounding.mode', _C.FINANCIAL, 'half_up', 'string', 'Monetary rounding mode'),
    # Locale
    ('locale.currency', _C.LOCALE, 'INR', 'string', 'Currency code'),
    # Branding (drives report PDF letterhead)
    ('branding.color_primary', _C.BRANDING, '#8B1A1A', 'string', 'Primary brand colour'),
    ('branding.company_name', _C.BRANDING, 'Thriive', 'string', 'Company name on reports'),
    ('branding.address', _C.BRANDING, '', 'string', 'Company address on reports'),
    # Security
    ('security.report_artifact_ttl_days', _C.SECURITY, 7, 'number', 'Report download expiry (days)'),
]

# No default flags: the partner portal is controlled by EntityType.display_config.portal_type,
# not a flag. Feature flags are a per-client toggle mechanism (SettingsService.is_enabled).
FLAGS_SEED = []


class Command(BaseCommand):
    help = 'Seed default system settings and feature flags.'

    def handle(self, *args, **options):
        for key, cat, value, vtype, desc in SETTINGS_SEED:
            SystemSetting.objects.update_or_create(
                key=key,
                defaults={'category': cat, 'value': value, 'value_type': vtype,
                          'description': desc, 'is_active': True},
            )
        for code, desc, enabled in FLAGS_SEED:
            FeatureFlag.objects.update_or_create(
                code=code, defaults={'description': desc, 'is_enabled': enabled, 'is_active': True})
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(SETTINGS_SEED)} settings, {len(FLAGS_SEED)} flags.'))
