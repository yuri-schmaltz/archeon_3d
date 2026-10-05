import React from 'react';
import type { JobResponse } from '../../api/types';
import { Text, Stack, StatusDot, type StatusKind, Pill } from '../../design/primitives';

interface JobRowProps {
    job: JobResponse;
    statusKind: StatusKind;
    onOpen: () => void;
    onReuse: () => void;
    t: (key: string, params?: Record<string, string | number>) => string;
}

function formatDate(iso: string | undefined): string {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
}

function formatAge(iso: string | undefined): string {
    if (!iso) return '—';
    const ms = Date.now() - new Date(iso).getTime();
    if (Number.isNaN(ms)) return '—';
    if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
    if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
    if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
    return `${Math.floor(ms / 86_400_000)}d`;
}

export const JobRow: React.FC<JobRowProps> = ({ job, statusKind, onOpen, onReuse, t }) => {
    return (
        <li
            role="listitem"
            className="group grid grid-cols-[2.25rem_1fr_auto] gap-4 py-3 hover:bg-surface-1/50 transition-colors duration-[120ms]"
        >
            <StatusDot kind={statusKind} size={8} className="self-center" />
            <button
                type="button"
                onClick={onOpen}
                className="text-left min-w-0 focus:outline-none focus-visible:bg-surface-1"
            >
                <Stack gap={1}>
                    <Stack direction="row" gap={2} align="center">
                        <Text
                            voice="mono"
                            size="2xs"
                            tone="muted"
                            tracking="widest"
                            uppercase
                        >
                            {job.uid.slice(0, 8)}
                        </Text>
                        {job.request_type && (
                            <Pill tone="muted">{job.request_type}</Pill>
                        )}
                        {job.stage && job.status === 'processing' && (
                            <Pill tone="accent">
                                {t(`stage.${job.stage}`, { defaultValue: job.stage })}
                            </Pill>
                        )}
                    </Stack>
                    <Text voice="body" size="sm" className="truncate">
                        {job.file_path ? job.file_path.split(/[\\/]/).pop() : '—'}
                    </Text>
                    <Stack direction="row" gap={2}>
                        <Text voice="mono" size="2xs" tone="dim">
                            {job.status}
                        </Text>
                        <Text voice="mono" size="2xs" tone="dim">
                            ·
                        </Text>
                        <Text voice="mono" size="2xs" tone="dim">
                            {formatAge(job.created_at)} atrás
                        </Text>
                        {job.completed_at && (
                            <>
                                <Text voice="mono" size="2xs" tone="dim">·</Text>
                                <Text voice="mono" size="2xs" tone="dim">
                                    {formatDate(job.completed_at)}
                                </Text>
                            </>
                        )}
                    </Stack>
                    {job.error && (
                        <Text voice="mono" size="2xs" tone="danger">
                            {job.error}
                        </Text>
                    )}
                </Stack>
            </button>
            <Stack direction="row" gap={2} align="center">
                <button
                    type="button"
                    onClick={onReuse}
                    title={t('library.reuse')}
                    className="text-fg-muted hover:text-fg focus:outline-none focus-visible:text-accent font-mono text-2xs uppercase tracking-wider px-2 py-1 border border-border rounded transition-colors"
                >
                    ↻ {t('library.reuse')}
                </button>
            </Stack>
        </li>
    );
};
