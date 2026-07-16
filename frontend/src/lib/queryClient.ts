import {QueryClient} from '@tanstack/react-query';

/**
 * Single app-wide React Query client. Exported as a module singleton so
 * non-React code (e.g. the auth store) can clear it on session change.
 */
export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
        },
    },
});
