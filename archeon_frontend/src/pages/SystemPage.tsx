import React, { useEffect, useState } from 'react';
import { apiClient, authHeaders, errorMessage } from '../api/client';
import { useT } from '../i18n';
import { SystemMonitor } from '../components/monitoring/SystemMonitor';
import {
    Text,
    Stack,
    Divider,
    Pill,
    Button,
} from '../design/primitives';

interface CapabilitiesLite {
    modes: Record<string, { available: boolean; reason: string | null }>;
    models: Record<string, { id: string; loaded: boolean }>;
    presets: Record<string, { steps: number; guidance: number; octree_resolution: number }>;
    limits: { image_bytes: number; mesh_bytes: number; queue_depth: number; body_bytes: number };
    version: string;
}

interface AdminStats {
    queue_depth: number;
    jobs_in_memory: number;
    jobs_in_store: number;
    by_status: Record<string, number>;
    persistence_enabled: boolean;
    model_loaded: boolean;
    max_history: number;
}

function formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KiB`;
    return `${(n / 1024 / 1024).toFixed(1)} MiB`;
}

export const SystemPage: React.FC = () => {
    const t = useT();
    const [stats, setStats] = useState<AdminStats | null>(null);
    const [capabilities, setCapabilities] = useState<CapabilitiesLite | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const reload = async () => {
        setBusy(true);
        setError(null);
        try {
            const [s, c] = await Promise.all([
                apiClient.get<AdminStats>('/admin/stats', { headers: authHeaders() }),
                apiClient.get<CapabilitiesLite>('/capabilities', { headers: authHeaders() }),
            ]);
            setStats(s.data);
            setCapabilities(c.data);
        } catch (err) {
            setError(errorMessage(err));
        } finally {
            setBusy(false);
        }
    };

    useEffect(() => {
        void reload();
        const id = setInterval(reload, 5_000);
        return () => clearInterval(id);
    }, []);

    return (
        <section className="space-y-6">
            <header className="space-y-1 flex items-start justify-between gap-4">
                <div className="space-y-1">
                    <Text as="h1" voice="display" size="xl" tracking="tight">
                        {t('system.heading')}
                    </Text>
                    <Text voice="body" size="sm" tone="muted">
                        {t('system.heading.hint')}
                    </Text>
                </div>
                <Button variant="ghost" size="sm" onClick={() => void reload()} disabled={busy}>
                    ↻ {t('common.refresh')}
                </Button>
            </header>

            {error && <Pill tone="danger">{error}</Pill>}

            <SystemMonitor />

            <Divider />

            <Stack gap={3}>
                <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                    {t('system.queue')}
                </Text>
                {stats && (
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <Metric label="Em fila" value={stats.queue_depth} />
                        <Metric label="Memória" value={stats.jobs_in_memory} />
                        <Metric label="Disco" value={stats.jobs_in_store} />
                        <Metric label="Histórico" value={stats.max_history} />
                    </div>
                )}
                {stats && typeof stats.by_status === 'object' && stats.by_status !== null && (
                    <div className="flex flex-wrap gap-2 pt-2">
                        {Object.entries(stats.by_status).map(([status, count]) => (
                            <Pill key={status} tone="muted">
                                {status}: {count}
                            </Pill>
                        ))}
                    </div>
                )}
            </Stack>

            <Divider />

            <Stack gap={3}>
                <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                    {t('system.models')}
                </Text>
                {capabilities && typeof capabilities.models === 'object' && capabilities.models !== null && (
                    <ul className="space-y-2">
                        {Object.entries(capabilities.models).map(([key, info]) => (
                            <li key={key} className="flex items-center gap-3">
                                <Pill tone={info.loaded ? 'accent' : 'muted'}>
                                    {info.loaded ? '✓' : '○'} {key}
                                </Pill>
                                <Text voice="mono" size="xs" tone="muted">
                                    {info.id}
                                </Text>
                            </li>
                        ))}
                    </ul>
                )}
            </Stack>

            <Divider />

            <Stack gap={3}>
                <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                    {t('system.persistence')}
                </Text>
                {capabilities && (
                    <ul className="space-y-2 text-sm">
                        <LimitRow label="Imagem máxima" value={formatBytes(capabilities.limits.image_bytes)} />
                        <LimitRow label="Mesh máximo" value={formatBytes(capabilities.limits.mesh_bytes)} />
                        <LimitRow label="Payload JSON máximo" value={formatBytes(capabilities.limits.body_bytes)} />
                        <LimitRow label="Profundidade da fila" value={String(capabilities.limits.queue_depth)} />
                        <LimitRow label="Versão" value={capabilities.version} />
                    </ul>
                )}
            </Stack>
        </section>
    );
};

const Metric: React.FC<{ label: string; value: number }> = ({ label, value }) => (
    <div className="border border-border rounded p-3 bg-surface-1/40">
        <Text voice="mono" size="2xs" tone="muted" tracking="wider" uppercase>
            {label}
        </Text>
        <Text voice="display" size="xl" tone="accent" className="tabular-nums">
            {value}
        </Text>
    </div>
);

const LimitRow: React.FC<{ label: string; value: string }> = ({ label, value }) => (
    <li className="flex justify-between border-b border-border py-1">
        <Text voice="mono" size="2xs" tone="muted" tracking="wider" uppercase>
            {label}
        </Text>
        <Text voice="mono" size="sm" tone="fg" className="tabular-nums">
            {value}
        </Text>
    </li>
);

export default SystemPage;
