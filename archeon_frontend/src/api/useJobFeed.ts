import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { apiClient, API_URL, authHeaders, errorMessage, requestAuthentication } from './client';

class UnsupportedStream extends Error {}
class AuthenticationError extends Error {}

interface FeedOptions<T> {
    enabled?: boolean;
    pollIntervalMs?: number;
    terminal?: (data: T) => boolean;
}

/** One stream, with polling during outages and automatic reconnection. */
export function useJobFeed<T>(path: string, event: string, options: FeedOptions<T> = {}) {
    const [data, setData] = useState<T | null>(null);
    const [connected, setConnected] = useState(false);
    const [isFallback, setIsFallback] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const fetchRef = useRef<() => void>(() => {});
    const { enabled = true, pollIntervalMs = 3000, terminal } = options;

    useEffect(() => {
        if (!enabled) return;
        let active = true;
        let stopped = false;
        let polling = false;
        let fetching = false;
        let failures = 0;
        let pollTimer: ReturnType<typeof setTimeout> | undefined;
        const lifecycle = new AbortController();
        const stream = new AbortController();
        setData(null);
        setLoading(true);
        setConnected(false);
        setIsFallback(false);
        setError(null);

        const stopPolling = () => {
            polling = false;
            clearTimeout(pollTimer);
        };
        const accept = (value: unknown) => {
            if (!active || stopped) return;
            // Guard against unexpected payload shapes (e.g. SPA HTML
            // fallback when the API isn't reachable in production).
            if (value !== null && value !== undefined && typeof value === 'object' && Array.isArray(value) === false && terminal === undefined) {
                // Heuristic: array-shaped endpoints are the common case here.
                // If no terminal check is registered and the payload is a
                // plain object (not array), treat it as a transient glitch.
                setError(errorMessage(new Error('Received an unexpected payload from the server.')));
                setLoading(false);
                return;
            }
            setData(value as T);
            setLoading(false);
            setError(null);
            if (terminal?.(value as T)) {
                stopped = true;
                stopPolling();
                stream.abort();
                setConnected(false);
            }
        };
        const fetchOnce = async () => {
            if (!active || stopped || fetching || document.hidden) return;
            fetching = true;
            try {
                const response = await apiClient.get<T>(path, { signal: lifecycle.signal });
                accept(response.data);
            } catch (err) {
                if (active && !lifecycle.signal.aborted) {
                    setError(errorMessage(err));
                    setLoading(false);
                }
            } finally {
                fetching = false;
            }
        };
        const startPolling = () => {
            if (polling || stopped || !active) return;
            polling = true;
            setIsFallback(true);
            const tick = async () => {
                if (!active || !polling || stopped) return;
                await fetchOnce();
                if (active && polling && !stopped) pollTimer = setTimeout(tick, pollIntervalMs);
            };
            void tick();
        };
        fetchRef.current = () => { void fetchOnce(); };
        const onVisible = () => { if (!document.hidden) void fetchOnce(); };
        document.addEventListener('visibilitychange', onVisible);

        void fetchEventSource(`${API_URL}${path}/events`, {
            signal: stream.signal,
            headers: authHeaders(),
            async onopen(response) {
                if (!active) return;
                if (response.status === 401 || response.status === 403) {
                    requestAuthentication();
                    throw new AuthenticationError('Authentication is required.');
                }
                if (response.status === 404 || response.status === 405) {
                    throw new UnsupportedStream('Live updates are unavailable; refreshing periodically.');
                }
                if (!response.ok || !response.headers.get('content-type')?.startsWith('text/event-stream')) {
                    throw new Error(`Live updates failed (HTTP ${response.status}).`);
                }
                failures = 0;
                stopPolling();
                setConnected(true);
                setIsFallback(false);
                setError(null);
            },
            onmessage(message) {
                if (message.event === event && active) accept(JSON.parse(message.data) as T);
            },
            onclose() {
                if (active && !stopped) throw new Error('Connection interrupted. Reconnecting…');
            },
            onerror(err) {
                if (!active || stopped) throw err;
                setConnected(false);
                if (err instanceof AuthenticationError || err instanceof UnsupportedStream) throw err;
                setError(errorMessage(err));
                startPolling();
                return Math.min(1000 * 2 ** failures++, 30_000);
            },
        }).catch((err: unknown) => {
            if (!active || stopped) return;
            setConnected(false);
            setError(errorMessage(err));
            setLoading(false);
            if (!(err instanceof AuthenticationError)) startPolling();
        });

        return () => {
            active = false;
            stopPolling();
            lifecycle.abort();
            stream.abort();
            document.removeEventListener('visibilitychange', onVisible);
            fetchRef.current = () => {};
        };
    }, [path, event, enabled, pollIntervalMs, terminal]);

    const refetch = useCallback(() => fetchRef.current(), []);
    return { data: enabled ? data : null, connected: enabled && connected,
        isFallback: enabled && isFallback, loading: enabled && loading, error, refetch };
}
