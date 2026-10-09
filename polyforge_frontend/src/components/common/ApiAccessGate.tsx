import { useEffect, useState } from 'react';
import axios from 'axios';
import { apiClient, BASE_URL, AUTH_REQUIRED_EVENT, setApiKey } from '../../api/client';
import { Button, Field, Text } from '../../design/primitives';
import { useT } from '../../i18n';

type GateState = 'checking' | 'offline' | 'locked' | 'ready';

/** Credentials stay in memory and are never included in the static bundle. */
export function ApiAccessGate({ children }: { children: React.ReactNode }) {
    const t = useT();
    const [state, setState] = useState<GateState>('checking');
    const [key, setKey] = useState('');
    const [message, setMessage] = useState('');
    const [busy, setBusy] = useState(false);
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        void axios
            .get(`${BASE_URL}/health`, { signal: controller.signal, timeout: 5000 })
            .then(({ data }) => setState(data.auth_required ? 'locked' : 'ready'))
            .catch(() => {
                if (!controller.signal.aborted) setState('offline');
            });
        const lock = () => {
            setState('locked');
            setApiKey('');
        };
        window.addEventListener(AUTH_REQUIRED_EVENT, lock);
        return () => {
            controller.abort();
            window.removeEventListener(AUTH_REQUIRED_EVENT, lock);
        };
    }, [attempt]);

    if (state === 'ready') return <>{children}</>;

    // aria-live label for the current state so screen readers announce changes.
    const alertRole = state === 'checking' ? 'status' : 'alert';
    const alertText =
        state === 'checking'
            ? t('auth.alert.connecting')
            : state === 'offline'
                ? t('auth.alert.offline')
                : t('auth.alert.locked');

    return (
        <main className="min-h-dvh flex items-center justify-center p-6">
            <div className="w-full max-w-sm space-y-5">
                <Text as="h1" voice="display" size="2xl">
                    {t('app.title')}
                </Text>
                <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                    {t('app.tagline')}
                </Text>

                <p role={alertRole} aria-live="polite" className="sr-only">
                    {alertText}
                </p>

                {state === 'checking' && (
                    <Text voice="body" size="sm" tone="muted" role="status">
                        {t('auth.connecting')}
                    </Text>
                )}

                {state === 'offline' && (
                    <div className="space-y-4">
                        <Text as="h2" voice="display" size="lg">
                            {t('auth.offline.title')}
                        </Text>
                        <Text voice="body" size="sm" tone="muted">
                            {t('auth.offline.body')}
                        </Text>
                        <Button
                            onClick={() => {
                                setState('checking');
                                setAttempt((n) => n + 1);
                            }}
                        >
                            {t('auth.reconnect')}
                        </Button>
                    </div>
                )}

                {state === 'locked' && (
                    <form
                        className="space-y-4"
                        onSubmit={async (event) => {
                            event.preventDefault();
                            if (busy || !key.trim()) return;
                            setBusy(true);
                            setMessage('');
                            setApiKey(key);
                            try {
                                await apiClient.get('/jobs');
                                setKey('');
                                setState('ready');
                            } catch {
                                setApiKey('');
                                setMessage(t('auth.error.invalid'));
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        <Text as="h2" voice="display" size="lg">
                            {t('auth.locked.title')}
                        </Text>
                        <Text voice="body" size="sm" tone="muted">
                            {t('auth.locked.body')}
                        </Text>
                        <Field
                            label={t('auth.field.label')}
                            type="password"
                            autoComplete="off"
                            required
                            value={key}
                            onChange={(event) => setKey(event.target.value)}
                        />
                        <Button
                            type="submit"
                            disabled={busy || !key.trim()}
                            block
                        >
                            {busy ? t('auth.submit.connecting') : t('auth.submit.connect')}
                        </Button>
                        {message && (
                            <Text voice="body" size="sm" tone="danger" role="alert">
                                {message}
                            </Text>
                        )}
                    </form>
                )}
            </div>
        </main>
    );
}
