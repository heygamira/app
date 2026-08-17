import { QueryClient } from '@tanstack/react-query';

// Single shared client for the app. Data here is family/health state that
// changes rarely within a session, so keep a short stale window and skip the
// noisy refetch-on-focus behaviour.
export const queryClientInstance = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30 * 1000,
    },
  },
});

export default queryClientInstance;
