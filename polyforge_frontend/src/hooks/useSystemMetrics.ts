/**
 * useSystemMetrics — small, reusable hook that polls /v1/system/metrics.
 *
 * Extracted from the older SystemMonitor component so other surfaces
 * (CapabilityStrip, StatusBar, etc.) can subscribe without duplicating
 * the fetch/cleanup logic.
 *
 * The hook is silent on failure: it exposes the error so the caller
 * can decide whether to render an "offline" indicator or to fall back
 * gracefully. It does not throw.
 */
import { useEffect, useState } from 'react';
import { apiClient } from '../api/client';
import type { SystemMetrics } from '../api/types';

const POLL_INTERVAL_MS = 4000;

export type SystemMetricsStatus =
  | 'loading'      // first poll in flight, no data yet
  | 'live'         // data is fresh
  | 'error';       // last poll failed

export interface UseSystemMetricsResult {
  metrics: SystemMetrics | null;
  error: string | null;
  loading: boolean;
  /** Lifecycle status: distinguishes "still loading" from "error" */
  status: SystemMetricsStatus;
  /** Force a refresh; resets the loading flag. */
  refresh: () => void;
}

export function useSystemMetrics(): UseSystemMetricsResult {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    const fetchOnce = async () => {
      try {
        const response = await apiClient.get<SystemMetrics>('/system/metrics', {
          signal: controller.signal,
        });
        if (!alive) return;
        setMetrics(response.data);
        setError(null);
      } catch (err) {
        if (!alive || controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
      } finally {
        if (alive) setLoading(false);
      }
    };
    void fetchOnce();
    const interval = setInterval(fetchOnce, POLL_INTERVAL_MS);
    return () => {
      alive = false;
      controller.abort();
      clearInterval(interval);
    };
  }, [nonce]);

  const status: SystemMetricsStatus = error
    ? 'error'
    : loading
      ? 'loading'
      : 'live';

  return {
    metrics,
    error,
    loading,
    status,
    refresh: () => {
      setLoading(true);
      setNonce((n) => n + 1);
    },
  };
}
