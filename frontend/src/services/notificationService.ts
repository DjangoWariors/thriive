import api from './api';
import type { PaginatedResponse } from '../types/api';
import type { AppNotification } from '../types/notification';

const BASE = '/api/v1/notifications';

export const notificationService = {
  async list(params?: { unread?: boolean; page?: number }): Promise<PaginatedResponse<AppNotification>> {
    const { data } = await api.get<PaginatedResponse<AppNotification>>(`${BASE}/`, { params });
    return data;
  },
  async unreadCount(): Promise<number> {
    const { data } = await api.get<{ count: number }>(`${BASE}/unread-count/`);
    return data.count;
  },
  async markRead(id: number): Promise<AppNotification> {
    const { data } = await api.post<AppNotification>(`${BASE}/${id}/read/`);
    return data;
  },
  async markAllRead(): Promise<void> {
    await api.post(`${BASE}/read-all/`);
  },
};
