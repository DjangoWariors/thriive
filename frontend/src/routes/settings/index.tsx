import { useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { PageHeader } from '../../components/ui/PageHeader';
import { Tabs } from '../../components/ui/Tabs';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import { ProfileTab } from './ProfileTab';
import { PasswordTab } from './PasswordTab';
import { NotificationsTab } from './NotificationsTab';
import { SystemTab } from './SystemTab';

export default function SettingsPage() {
  const { user } = useAuth();
  const { can } = useRBAC();
  const [searchParams, setSearchParams] = useSearchParams();

  const showPassword = user?.has_password !== false; // hide only for OTP-only accounts
  const showSystem = can('system_admin');

  const tabs = useMemo(() => {
    const t = [{ label: 'Profile', value: 'profile' }];
    if (showPassword) t.push({ label: 'Password', value: 'password' });
    t.push({ label: 'Notifications', value: 'notifications' });
    if (showSystem) t.push({ label: 'System', value: 'system' });
    return t;
  }, [showPassword, showSystem]);

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
      {active === 'notifications' && <NotificationsTab />}
      {active === 'system' && showSystem && <SystemTab />}
    </div>
  );
}
