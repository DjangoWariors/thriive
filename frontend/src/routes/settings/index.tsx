import { useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { PageHeader } from '../../components/ui/PageHeader';
import { Tabs } from '../../components/ui/Tabs';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import { ProfileTab } from './ProfileTab';
import { PasswordTab } from './PasswordTab';
import { ApiKeysTab } from './ApiKeysTab';
import { DeliveryTargetsTab } from './DeliveryTargetsTab';
import { IntegrationMonitorTab } from './IntegrationMonitorTab';

export default function SettingsPage() {
  const { user } = useAuth();
  const { can } = useRBAC();
  const [searchParams, setSearchParams] = useSearchParams();

  const showPassword = user?.has_password !== false; // hide only for OTP-only accounts
  const showIntegrationKeys = can('system_admin');
  const showIntegrationMonitor = can('integration_monitor');

  const tabs = useMemo(() => {
    const t = [{ label: 'Profile', value: 'profile' }];
    if (showPassword) t.push({ label: 'Password', value: 'password' });
    if (showIntegrationKeys) {
      t.push({ label: 'API Keys', value: 'api-keys' });
      t.push({ label: 'Delivery Targets', value: 'delivery-targets' });
    }
    if (showIntegrationMonitor) t.push({ label: 'Integration Monitor', value: 'integration-monitor' });
    return t;
  }, [showPassword, showIntegrationKeys, showIntegrationMonitor]);

  const requested = searchParams.get('tab');
  const active = tabs.some((t) => t.value === requested) ? (requested as string) : 'profile';

  const setActive = (value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', value);
      return next;
    });
  };

  return (
    <div className="p-6">
      <PageHeader title="Settings" description="Manage your account and platform configuration." />

      <Tabs tabs={tabs} activeTab={active} onChange={setActive} className="mb-6" />

      {active === 'profile' && <ProfileTab />}
      {active === 'password' && showPassword && <PasswordTab />}
      {active === 'api-keys' && showIntegrationKeys && <ApiKeysTab />}
      {active === 'delivery-targets' && showIntegrationKeys && <DeliveryTargetsTab />}
      {active === 'integration-monitor' && showIntegrationMonitor && <IntegrationMonitorTab />}
    </div>
  );
}
