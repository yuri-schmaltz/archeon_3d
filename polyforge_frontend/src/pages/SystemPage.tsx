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
    limits: { image_bytes: number; mesh_bytes: number; queue_depth: number; body_bytes: number | null };
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

interface ModelStatus {
    loaded: boolean;
    loading: boolean;
    model: string;
    subfolder: string | null;
    device: string;
    text_to_image_loaded?: boolean;
    text_to_image_model?: string | null;
    last_error: string | null;
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
    const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [warmupBusy, setWarmupBusy] = useState(false);
    const [warmupMessage, setWarmupMessage] = useState<string | null>(null);

    const reload = async () => {
        setBusy(true);
        setError(null);
        try {
            const [s, c, m] = await Promise.all([
                apiClient.get<AdminStats>('/admin/stats', { headers: authHeaders() }),
                apiClient.get<CapabilitiesLite>('/capabilities', { headers: authHeaders() }),
                apiClient
                    .get<ModelStatus>('/models/status', { headers: authHeaders() })
                    .catch(() => null),
            ]);
            setStats(s.data);
            setCapabilities(c.data);
            setModelStatus(m?.data ?? null);
        } catch (err) {
            setError(errorMessage(err));
        } finally {
            setBusy(false);
        }
    };

    const triggerWarmup = async () => {
        setWarmupBusy(true);
        setWarmupMessage(null);
        try {
            const res = await apiClient.post<{ status: string; model: string }>(
                '/models/load',
                {},
                { headers: authHeaders() },
            );
            if (res.data.status === 'already_loaded') {
                setWarmupMessage('Modelo já está carregado.');
            } else {
                setWarmupMessage(
                    `Carregando ${res.data.model}… o download pode levar alguns minutos na primeira vez.`,
                );
            }
            // Auto-refresh after a few seconds so the loaded flag updates.
            setTimeout(() => void reload(), 4_000);
        } catch (err) {
            setWarmupMessage(`Falha ao iniciar: ${errorMessage(err)}`);
        } finally {
            setWarmupBusy(false);
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
                <div className="flex items-center justify-between gap-3 flex-wrap">
                    <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                        {t('system.models')}
                    </Text>
                    <Button
                        data-testid="warmup-button"
                        variant={modelStatus?.loaded ? 'ghost' : 'primary'}
                        size="sm"
                        onClick={() => void triggerWarmup()}
                        disabled={warmupBusy}
                    >
                        {warmupBusy
                            ? 'Iniciando…'
                            : modelStatus?.loaded
                            ? 'Recarregar modelo'
                            : 'Carregar modelo agora'}
                    </Button>
                </div>

                {modelStatus && (
                    <div
                        data-testid="model-status-card"
                        className="border border-border rounded p-3 bg-surface-1/30 space-y-2"
                    >
                        <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
                            <Pill tone={modelStatus.loaded ? 'accent' : 'muted'}>
                                {modelStatus.loaded ? '✓ carregado' : '○ não carregado'}
                            </Pill>
                            <Text voice="mono" size="xs" tone="muted">
                                {modelStatus.model}
                                {modelStatus.subfolder ? ` / ${modelStatus.subfolder}` : ''}
                            </Text>
                            <Pill tone="muted">{modelStatus.device}</Pill>
                            {modelStatus.text_to_image_model && (
                                <Pill tone={modelStatus.text_to_image_loaded ? 'accent' : 'muted'}>
                                    {modelStatus.text_to_image_loaded ? '✓ texto-para-imagem' : '○ texto-para-imagem'}
                                </Pill>
                            )}
                            {modelStatus.text_to_image_model && (
                                <Text voice="mono" size="xs" tone="muted">
                                    {modelStatus.text_to_image_model}
                                </Text>
                            )}
                        </div>
                        {warmupMessage && (
                            <Text voice="body" size="xs" tone="muted">
                                {warmupMessage}
                            </Text>
                        )}
                        {modelStatus.last_error && (
                            <Pill tone="danger">
                                Último erro: {modelStatus.last_error}
                            </Pill>
                        )}
                    </div>
                )}

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
                        <LimitRow
                            label="Payload JSON máximo"
                            value={
                                capabilities.limits.body_bytes === null
                                    ? t('system.unlimited')
                                    : formatBytes(capabilities.limits.body_bytes)
                            }
                        />
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
