import api from './api';
import type { AuthTokens, User } from '../types/auth';
import type { PermissionCatalog } from '../types/admin';

export const authService = {
  async login(identifier: string, password: string): Promise<AuthTokens> {
    const { data } = await api.post<AuthTokens>('/api/v1/auth/login/', { identifier, password });
    return data;
  },

  async requestOTP(identifier: string): Promise<{ message: string }> {
    const { data } = await api.post<{ message: string }>('/api/v1/auth/login/otp/request/', {
      identifier,
    });
    return data;
  },

  async verifyOTP(identifier: string, otp: string): Promise<AuthTokens> {
    const { data } = await api.post<AuthTokens>('/api/v1/auth/login/otp/verify/', {
      identifier,
      otp,
    });
    return data;
  },

  async logout(refresh: string): Promise<void> {
    await api.post('/api/v1/auth/logout/', { refresh });
  },

  async me(): Promise<User> {
    const { data } = await api.get<User>('/api/v1/auth/me/');
    return data;
  },

  async updateMe(payload: {
    first_name?: string;
    last_name?: string;
    designation?: string;
    department?: string;
  }): Promise<User> {
    const { data } = await api.patch<User>('/api/v1/auth/me/', payload);
    return data;
  },

  async changePassword(oldPassword: string, newPassword: string): Promise<void> {
    await api.post('/api/v1/auth/me/change-password/', {
      old_password: oldPassword,
      new_password: newPassword,
    });
  },

  async permissionCatalog(): Promise<PermissionCatalog> {
    const { data } = await api.get<PermissionCatalog>('/api/v1/auth/permission-catalog/');
    return data;
  },
};
