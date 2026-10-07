import { useEffect, useState } from 'react';
import axios from 'axios';
import { apiClient, BASE_URL, AUTH_REQUIRED_EVENT, setApiKey } from '../../api/client';
import { Button, Field, Text } from '../../design/primitives';

/** Credentials stay in memory and are never included in the static bundle. */
export function ApiAccessGate({ children }: { children: React.ReactNode }) {
    const [state, setState] = useState<'checking' | 'offline' | 'locked' | 'ready'>('checking');
    const [key, setKey] = useState('');
    const [message, setMessage] = useState('');
    const [busy, setBusy] = useState(false);
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        void axios.get(`${BASE_URL}/health`, { signal: controller.signal, timeout: 5000 })
            .then(({ data }) => setState(data.auth_required ? 'locked' : 'ready'))
            .catch(() => { if (!controller.signal.aborted) setState('offline'); });
        const lock = () => { setState('locked'); setApiKey(''); };
        window.addEventListener(AUTH_REQUIRED_EVENT, lock);
        return () => {
            controller.abort();
            window.removeEventListener(AUTH_REQUIRED_EVENT, lock);
        };
    }, [attempt]);

    if (state === 'ready') return children;
    return (
        <main className="min-h-dvh flex items-center justify-center p-6">
            <div className="w-full max-w-sm space-y-5">
                <Text as="h1" voice="display" size="2xl">PolyForge</Text>
                {state === 'checking' && <p role="status">Connecting to the generation server…</p>}
                {state === 'offline' && <>
                    <p role="alert">The generation server is unavailable. Check that the backend is running.</p>
                    <Button onClick={() => { setState('checking'); setAttempt((n) => n + 1); }}>Reconnect</Button>
                </>}
                {state === 'locked' && <form className="space-y-4" onSubmit={async (event) => {
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
                        setMessage('Could not connect. Check the API key and try again.');
                    } finally { setBusy(false); }
                }}>
                    <p>This server requires an API key.</p>
                    <Field label="API key" type="password" autoComplete="off" required
                        value={key} onChange={(event) => setKey(event.target.value)} />
                    <Button type="submit" disabled={busy || !key.trim()} block>
                        {busy ? 'Connecting…' : 'Connect'}
                    </Button>
                    {message && <p role="alert" className="text-danger text-sm">{message}</p>}
                </form>}
            </div>
        </main>
    );
}
