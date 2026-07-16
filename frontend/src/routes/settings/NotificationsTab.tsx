import { useEffect, useState } from 'react';
import { BellOff } from 'lucide-react';
import { Card } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { EmptyState } from '../../components/ui/EmptyState';
import {TableSkeleton} from '../../components/ui/Skeleton';
import { useNotificationPrefs, useUpdateNotificationPrefs } from '../../hooks/useNotifications';
import type { NotificationPrefs } from '../../types/settings';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const CHANNEL_LABELS: Record<string, string> = {
  in_app: 'In-app',
  email: 'Email',
};

function titleCase(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function NotificationsTab() {
  const { data, isLoading } = useNotificationPrefs();
  const update = useUpdateNotificationPrefs();
  const [draft, setDraft] = useState<NotificationPrefs>({});

  useEffect(() => {
    if (data) setDraft(data.prefs ?? {});
  }, [data]);

  if (isLoading || !data) {
    return (
      <TableSkeleton/>
    );
  }

  // SMS is a backend enum but no gateway is wired — don't offer a toggle that does nothing.
  const available_categories = data.available_categories;
  const channels = data.channels.filter((ch) => ch !== 'sms');

  if (available_categories.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={BellOff}
          title="No notification types yet"
          description="Notification preferences appear here once the platform has notification templates configured."
        />
      </Card>
    );
  }

  // Missing keys default to opted-in.
  const isOn = (cat: string, ch: string) => draft[cat]?.[ch] ?? true;

  const toggle = (cat: string, ch: string) => {
    setDraft((prev) => ({
      ...prev,
      [cat]: { ...prev[cat], [ch]: !(prev[cat]?.[ch] ?? true) },
    }));
  };

  const save = () => {
    update.mutate(draft, {
      onSuccess: () => notify.success('Notification preferences saved'),
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not save preferences')),
    });
  };

  return (
    <Card
      title="Notification preferences"
      subtitle="Choose which notifications you receive, by type and channel."
      padding="none"
    >
      <table className="w-full text-left text-sm">
        <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500">
          <tr>
            <th className="px-6 py-3">Type</th>
            {channels.map((ch) => (
              <th key={ch} className="px-4 py-3 text-center">
                {CHANNEL_LABELS[ch] ?? titleCase(ch)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {available_categories.map((cat) => (
            <tr key={cat} className="hover:bg-gray-50">
              <td className="px-6 py-3 font-medium text-gray-900">{titleCase(cat)}</td>
              {channels.map((ch) => (
                <td key={ch} className="px-4 py-3 text-center">
                  <input
                    type="checkbox"
                    className="h-4 w-4 cursor-pointer accent-primary"
                    checked={isOn(cat, ch)}
                    onChange={() => toggle(cat, ch)}
                    aria-label={`${titleCase(cat)} via ${CHANNEL_LABELS[ch] ?? ch}`}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex justify-end border-t border-gray-100 px-6 py-4">
        <Button onClick={save} loading={update.isPending}>
          Save preferences
        </Button>
      </div>
    </Card>
  );
}
