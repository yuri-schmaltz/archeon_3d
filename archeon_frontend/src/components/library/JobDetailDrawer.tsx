import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { apiClient, BASE_URL, errorMessage, authHeaders } from '../../api/client';
import type { JobResponse } from '../../api/types';
import { useT } from '../../i18n';
import {
    Text,
    Stack,
    Button,
    Divider,
    Pill,
} from '../../design/primitives';
import { MeshPreview } from '../jobs/MeshPreview';

interface JobDetailDrawerProps {
    uid: string | null;
    onClose: () => void;
}

function previewUrl(job: JobResponse | null): string | null {
    if (!job?.file_path) return null;
    const fname = job.file_path.split(/[\\/]/).pop();
    return `${BASE_URL}/files/${encodeURIComponent(fname ?? "")}`;
}

function formatSeconds(ms: number | null | undefined): string {
    if (ms == null || Number.isNaN(ms)) return '—';
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function durationMs(job: JobResponse): number | null {
    if (!job.created_at || !job.completed_at) return null;
    const start = new Date(job.created_at).getTime();
    const end = new Date(job.completed_at).getTime();
    if (Number.isNaN(start) || Number.isNaN(end)) return null;
    return end - start;
}

export const JobDetailDrawer: React.FC<JobDetailDrawerProps> = ({ uid, onClose }) => {
    const t = useT();
    const [job, setJob] = useState<JobResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [showPreview, setShowPreview] = useState(false);

    useEffect(() => {
        if (!uid) {
            // Reset via a microtask to avoid setState-in-effect warnings
            // (the change is driven by `uid`, not the effect body).
            queueMicrotask(() => setJob(null));
            return;
        }
        let active = true;
        const controller = new AbortController();
        queueMicrotask(() => setError(null));
        apiClient
            .get<JobResponse>(`/jobs/${encodeURIComponent(uid)}`, {
                headers: authHeaders(),
                signal: controller.signal,
            })
            .then((response) => {
                if (!active) return;
                setJob(response.data);
            })
            .catch((err: unknown) => {
                if (!active || controller.signal.aborted) return;
                if ((err as { code?: string }).code === 'ERR_CANCELED') return;
                setError(errorMessage(err));
            });
        return () => {
            active = false;
            controller.abort();
        };
    }, [uid]);

    useEffect(() => {
        if (!uid) return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [uid, onClose]);

    const src = previewUrl(job);

    return (
        <AnimatePresence>
            {uid && (
                <>
                    <motion.div
                        key="backdrop"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.15 }}
                        className="fixed inset-0 bg-bg/70 z-40"
                        onClick={onClose}
                        aria-hidden="true"
                    />
                    <motion.aside
                        key="drawer"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="job-detail-title"
                        initial={{ x: '100%' }}
                        animate={{ x: 0 }}
                        exit={{ x: '100%' }}
                        transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
                        className="fixed right-0 top-0 bottom-0 w-full max-w-md bg-bg border-l border-border z-50 overflow-y-auto"
                    >
                        <header className="px-5 py-4 flex items-center justify-between border-b border-border">
                            <Text
                                as="h2"
                                voice="display"
                                size="lg"
                                tracking="tight"
                                id="job-detail-title"
                            >
                                {t('library.detail')}
                            </Text>
                            <button
                                type="button"
                                aria-label={t('common.close')}
                                onClick={onClose}
                                className="text-fg-muted hover:text-fg font-mono text-2xs uppercase tracking-widest px-2 py-1"
                            >
                                ✕
                            </button>
                        </header>

                        {error && (
                            <div className="px-5 py-3">
                                <Pill tone="danger">{error}</Pill>
                            </div>
                        )}

                        {job && (
                            <div className="px-5 py-4 space-y-4">
                                <Stack gap={1}>
                                    <Text voice="mono" size="2xs" tone="muted" uppercase tracking="widest">
                                        {t('library.detail')}
                                    </Text>
                                    <Text
                                        voice="mono"
                                        size="sm"
                                        tone="fg"
                                        className="break-all"
                                    >
                                        {job.uid}
                                    </Text>
                                </Stack>
                                <Divider />
                                <Stack gap={2}>
                                    <Row label="Status" value={job.status} />
                                    <Row
                                        label="Tipo"
                                        value={job.request_type ?? 'unknown'}
                                    />
                                    {job.stage && (
                                        <Row
                                            label="Etapa"
                                            value={t(`stage.${job.stage}`, { defaultValue: job.stage })}
                                        />
                                    )}
                                    {job.stage_progress != null && (
                                        <Row
                                            label="Progresso"
                                            value={`${Math.round(job.stage_progress * 100)}%`}
                                        />
                                    )}
                                    <Row label="Criado em" value={job.created_at} />
                                    {job.completed_at && (
                                        <Row
                                            label="Concluído em"
                                            value={job.completed_at}
                                        />
                                    )}
                                    <Row
                                        label="Duração"
                                        value={formatSeconds(durationMs(job))}
                                    />
                                    {job.error && (
                                        <Row
                                            label="Erro"
                                            value={job.error}
                                            danger
                                        />
                                    )}
                                </Stack>

                                {src && (
                                    <>
                                        <Divider />
                                        <Stack gap={2}>
                                            <Button
                                                variant="secondary"
                                                size="sm"
                                                onClick={() => setShowPreview((s) => !s)}
                                            >
                                                {showPreview
                                                    ? t('library.preview.close')
                                                    : t('library.preview')}
                                            </Button>
                                            {showPreview && (
                                                <MeshPreview src={src} alt={job.uid} height={220} />
                                            )}
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={() => window.open(src, '_blank')}
                                            >
                                                ↓ {t('library.download')}
                                            </Button>
                                        </Stack>
                                    </>
                                )}
                            </div>
                        )}
                    </motion.aside>
                </>
            )}
        </AnimatePresence>
    );
};

const Row: React.FC<{ label: string; value: string; danger?: boolean }> = ({ label, value, danger }) => (
    <Stack direction="row" gap={3} align="baseline" className="text-sm">
        <Text
            voice="mono"
            size="2xs"
            tone="muted"
            tracking="wider"
            uppercase
            className="shrink-0 w-24"
        >
            {label}
        </Text>
        <Text
            voice="mono"
            size="xs"
            tone={danger ? 'danger' : 'fg'}
            className="break-all min-w-0"
        >
            {value}
        </Text>
    </Stack>
);
