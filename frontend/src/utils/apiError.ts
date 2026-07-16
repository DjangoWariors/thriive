import {isAxiosError} from 'axios';


export function apiErrorMessage(err: unknown, fallback: string): string {
    if (isAxiosError(err)) {
        const data = err.response?.data;
        if (data && typeof data === 'object') {
            const detail = (data as Record<string, unknown>).detail;
            if (typeof detail === 'string') return detail;
            const first = Object.values(data)[0];
            if (Array.isArray(first) && typeof first[0] === 'string') return first[0];
            if (typeof first === 'string') return first;
        }
    }
    return fallback;
}
