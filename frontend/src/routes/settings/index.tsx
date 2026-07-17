import { useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { PageHeader } from '../../components/ui/PageHeader';
import { Tabs } from '../../components/ui/Tabs';
import { useAuth } from '../../hooks/useAuth';
import { ProfileTab } from './ProfileTab';
import { PasswordTab } from './PasswordTab';

export default function SettingsPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const showPassword = user?.has_password !== false; // hide only for OTP-only accounts

  const tabs = useMemo(() => {
    const t = [{ label: 'Profile', value: 'profile' }];
    if (showPassword) t.push({ label: 'Password', value: 'password' });
    return t;
  }, [showPassword]);

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
    </div>
  );
}
