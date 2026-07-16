import {create} from 'zustand';
import {authService} from '../services/auth';
import {queryClient} from '../lib/queryClient';
import type {User} from '../types/auth';

interface AuthState {
    user: User | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    login: (identifier: string, password: string) => Promise<void>;
    loginOTP: (identifier: string, otp: string) => Promise<void>;
    logout: () => Promise<void>;
    fetchUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()((set) => ({
    user: null,
    isAuthenticated: Boolean(localStorage.getItem('access_token')),
    isLoading: false,

    login: async (identifier, password) => {
        set({isLoading: true});
        queryClient.clear();
        try {
            const tokens = await authService.login(identifier, password);
            localStorage.setItem('access_token', tokens.access);
            localStorage.setItem('refresh_token', tokens.refresh);
            const user = await authService.me();
            set({user, isAuthenticated: true});
        } finally {
            set({isLoading: false});
        }
    },

    loginOTP: async (identifier, otp) => {
        set({isLoading: true});
        queryClient.clear();
        try {
            const tokens = await authService.verifyOTP(identifier, otp);
            localStorage.setItem('access_token', tokens.access);
            localStorage.setItem('refresh_token', tokens.refresh);
            const user = await authService.me();
            set({user, isAuthenticated: true});
        } finally {
            set({isLoading: false});
        }
    },

    logout: async () => {
        const refresh = localStorage.getItem('refresh_token');
        if (refresh) {
            try {
                await authService.logout(refresh);
            } catch {

            }
        }
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        queryClient.clear();
        set({user: null, isAuthenticated: false});
    },

    fetchUser: async () => {
        set({isLoading: true});
        try {
            const user = await authService.me();
            set({user, isAuthenticated: true});
        } catch {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            set({user: null, isAuthenticated: false});
        } finally {
            set({isLoading: false});
        }
    },
}));
