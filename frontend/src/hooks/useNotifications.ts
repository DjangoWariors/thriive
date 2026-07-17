import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notificationService } from '../services/notificationService';

export function useUnreadCount() {
  return useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: () => notificationService.unreadCount(),
    refetchInterval: 60_000,
  });
}

export function useNotifications(params?: { unread?: boolean }) {
  return useQuery({
    queryKey: ['notifications', 'list', params ?? {}],
    queryFn: () => notificationService.list(params),
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ['notifications'] });
}

export function useMarkRead() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (id: number) => notificationService.markRead(id), onSuccess: invalidate });
}

export function useMarkAllRead() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: () => notificationService.markAllRead(), onSuccess: invalidate });
}
