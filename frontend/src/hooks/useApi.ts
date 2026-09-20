/** Data-fetching hooks for the operational views.
 *
 * Deliberately small rather than a data library: the prototype has no cache
 * invalidation problem worth solving, and an explicit loading/error/data triple
 * keeps every page's states visible instead of hidden behind a provider.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { extractError } from '../utils/api';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Runs `fetcher` on mount and whenever `deps` change.
 *
 * Late responses from a superseded request are discarded — without this, a
 * slow first request can land after a fast second one and overwrite it.
 */
export function useApi<T>(
  fetcher: () => Promise<{ data: T }>,
  deps: unknown[] = []
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const requestId = useRef(0);

  // The fetcher is typically an inline arrow, so it is intentionally not a
  // dependency — callers control re-fetching through `deps` and `reload`.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    const id = ++requestId.current;
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetcherRef
      .current()
      .then((res) => {
        if (cancelled || id !== requestId.current) return;
        setData(res.data);
      })
      .catch((err) => {
        if (cancelled || id !== requestId.current) return;
        setData(null);
        setError(
          axios.isAxiosError(err) ? extractError(err) : 'Request failed'
        );
      })
      .finally(() => {
        if (cancelled || id !== requestId.current) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  return { data, loading, error, reload };
}

/**
 * Wraps a one-shot mutation (decide, resolve, submit…) with pending and error
 * state so a page does not have to hand-roll it in every handler.
 */
export function useMutation<Args extends unknown[], Result>(
  fn: (...args: Args) => Promise<Result>
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (...args: Args): Promise<Result | null> => {
      setPending(true);
      setError(null);
      try {
        return await fn(...args);
      } catch (err) {
        setError(axios.isAxiosError(err) ? extractError(err) : 'Request failed');
        return null;
      } finally {
        setPending(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  return { run, pending, error, clearError: () => setError(null) };
}
