import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Bell } from 'lucide-react';
import { useMarkAllRead, useMarkRead, useNotifications, useUnreadCount } from '../../hooks/useNotifications';
import { cn } from '../../utils/cn';
import { NotificationIcon } from '../../utils/notificationIcons';

export function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { data: count } = useUnreadCount();
  const { data: resp } = useNotifications();
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();

  const items = resp?.results ?? [];
  const unread = count ?? 0;

  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)}
              className="relative rounded-lg p-2 text-gray-500 hover:bg-gray-100" aria-label="Notifications">
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-30 mt-2 w-80 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg">
            <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
              <span className="text-sm font-semibold text-gray-900">Notifications</span>
              {unread > 0 && (
                <button onClick={() => markAll.mutate()} className="text-xs text-primary hover:underline">
                  Mark all read
                </button>
              )}
            </div>
            <div className="max-h-96 overflow-auto">
              {items.length === 0 ? (
                <p className="px-3 py-8 text-center text-sm text-gray-400">You're all caught up.</p>
              ) : (
                items.map((n) => (
                  <button key={n.id}
                    onClick={() => {
                      if (!n.is_read) markRead.mutate(n.id);
                      if (n.link) { setOpen(false); navigate(n.link); }
                    }}
                    className={cn('flex w-full items-start gap-2.5 border-b border-gray-50 px-3 py-2 text-left hover:bg-gray-50',
                      !n.is_read && 'bg-primary-50')}>
                    <NotificationIcon category={n.category} className="mt-0.5 h-4 w-4 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900">{n.title}</p>
                      {n.body && <p className="truncate text-xs text-gray-500">{n.body}</p>}
                      <p className="mt-0.5 text-[10px] text-gray-500">{n.created_at.slice(0, 16).replace('T', ' ')}</p>
                    </div>
                    {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" aria-label="unread" />}
                  </button>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
