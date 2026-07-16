import '@testing-library/jest-dom/vitest';
import {afterEach} from 'vitest';
import {cleanup} from '@testing-library/react';

// This environment exposes no Web Storage (Node's bare `localStorage` global shadows
// jsdom's, and window.localStorage is absent too) — back it with an in-memory store
// so modules touching storage at import time (authStore) work.
if (typeof globalThis.localStorage === 'undefined' || typeof window.localStorage === 'undefined') {
    const store = new Map<string, string>();
    const memoryStorage: Storage = {
        get length() { return store.size; },
        clear: () => store.clear(),
        getItem: (k) => store.get(k) ?? null,
        key: (i) => [...store.keys()][i] ?? null,
        removeItem: (k) => void store.delete(k),
        setItem: (k, v) => void store.set(k, String(v)),
    };
    for (const target of [globalThis, window]) {
        Object.defineProperty(target, 'localStorage', {
            value: memoryStorage, configurable: true, writable: true,
        });
    }
}

// jsdom has no layout engine; stub the scrolling APIs components call in effects.
if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
}

// Unmount React trees between tests so renders don't leak into one another.
afterEach(() => cleanup());
