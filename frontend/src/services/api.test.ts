import {describe, expect, it} from 'vitest';
import api from './api';

/**
 * A 200k-entity CSV export takes ~40s to stream, so the 30s default that suits a
 * JSON call aborted it mid-download and surfaced as "Could not export entities."
 * Downloads must instead give up when Nginx does (proxy_read_timeout 300s).
 */
describe('api request interceptor', () => {
    // Interceptors are registered as {fulfilled, rejected} pairs on the axios instance.
    const runRequestInterceptors = (config: Record<string, unknown>) => {
        const handlers = (
            api.interceptors.request as unknown as {
                handlers: ({fulfilled: (c: unknown) => unknown } | null)[];
            }
        ).handlers;
        return handlers
            .filter((h): h is {fulfilled: (c: unknown) => unknown} => h !== null)
            .reduce((acc, h) => h.fulfilled(acc), {headers: {}, ...config}) as Record<string, unknown>;
    };

    it('gives blob downloads the 300s Nginx budget, not the 30s JSON default', () => {
        expect(runRequestInterceptors({responseType: 'blob'}).timeout).toBe(300_000);
    });

    it('leaves ordinary JSON requests on the instance default', () => {
        expect(runRequestInterceptors({}).timeout).toBeUndefined();
        expect(api.defaults.timeout).toBe(30_000);
    });
});
