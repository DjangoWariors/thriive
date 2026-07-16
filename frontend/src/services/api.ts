import axios from 'axios';
import type {AxiosResponse, InternalAxiosRequestConfig} from 'axios';

interface QueueItem {
    resolve: (token: string) => void;
    reject: (error: unknown) => void;
}

type RetryableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

let isRefreshing = false;
let failedQueue: QueueItem[] = [];

function processQueue(error: unknown, token: string | null): void {
    for (const item of failedQueue) {
        if (token === null) {
            item.reject(error ?? new Error('Token refresh failed'));
        } else {
            item.resolve(token);
        }
    }
    failedQueue = [];
}

const BASE_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

const api = axios.create({
    baseURL: BASE_URL,
    timeout: 30_000,
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('access_token');
    if (token !== null) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

api.interceptors.response.use(
    (response: AxiosResponse) => response,
    async (error: unknown) => {
        if (!axios.isAxiosError(error)) return Promise.reject(error);

        const config = error.config as RetryableConfig | undefined;


        const wasAuthenticated =
            typeof config?.headers?.Authorization === 'string' &&
            config.headers.Authorization.startsWith('Bearer ');

        if (!config || error.response?.status !== 401 || config._retry === true || !wasAuthenticated) {
            return Promise.reject(error);
        }

        if (isRefreshing) {
            return new Promise<AxiosResponse>((outerResolve, outerReject) => {
                failedQueue.push({
                    resolve: (token) => {
                        config.headers.Authorization = `Bearer ${token}`;
                        outerResolve(api(config));
                    },
                    reject: outerReject,
                });
            });
        }

        config._retry = true;
        isRefreshing = true;

        const refreshToken = localStorage.getItem('refresh_token');

        if (!refreshToken) {
            processQueue(new Error('No refresh token available'), null);
            isRefreshing = false;
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.href = '/login';
            return Promise.reject(error);
        }

        try {
            const {data} = await axios.post<{ access: string; refresh?: string }>(
                `${BASE_URL}/api/v1/auth/token/refresh/`,
                {refresh: refreshToken},
            );
            localStorage.setItem('access_token', data.access);
            if (data.refresh) {
                localStorage.setItem('refresh_token', data.refresh);
            }
            config.headers.Authorization = `Bearer ${data.access}`;
            processQueue(null, data.access);
            return api(config);
        } catch (refreshError) {
            processQueue(refreshError, null);
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.href = '/login';
            return Promise.reject(refreshError);
        } finally {
            isRefreshing = false;
        }
    },
);

export default api;
