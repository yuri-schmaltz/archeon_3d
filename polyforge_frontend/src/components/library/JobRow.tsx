import React, { useState } from 'react';
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

/**
 * Renders a job's error message without burying the row in 20+ lines
 * of traceback. The first line (or first 240 chars) is shown
 * collapsed; clicking the chevron reveals the full text.
 *
 * Why we don't truncate blindly: real failures can be a long
 * diffusers / transformers incompatibility string, but the
 * actionable line is usually right at the top (e.g.
 * ``ModuleNotFoundError: No module named 'diffusers'``). Surfacing
 * the first line + a "show more" link is the best compromise.
 */
const ErrorLine: React.FC<{ error: string }> = ({ error }) => {
    const [open, setOpen] = useState(false);
    const firstLine = error.split('\n', 1)[0].trim();
    // If the error is a single short line just show it. Otherwise
    // collapse to the first line + a disclosure.
    const isLong = error.length > 240 || error.includes('\n');
    if (!isLong) {
        return (
            <Text voice="mono" size="2xs" tone="danger" className="break-words">
                {error}
            </Text>
        );
    }
    return (
        <div
            className="space-y-1"
            // The outer row is a <button> that opens the drawer; without
            // stopping propagation the inner disclosure would also
            // trigger the drawer when the user is just trying to read
            // the full error.
            onClick={(event) => event.stopPropagation()}
        >
            <Text voice="mono" size="2xs" tone="danger" className="break-words">
                {firstLine}
            </Text>
            {open ? (
                <Text
                    voice="mono"
                    size="2xs"
                    tone="dim"
                    className="break-words whitespace-pre-wrap max-h-48 overflow-y-auto border border-border rounded p-2 bg-surface-1/40"
                >
                    {error}
                </Text>
            ) : null}
            <button
                type="button"
                onClick={(event) => {
                    event.stopPropagation();
                    setOpen((v) => !v);
                }}
                className="font-mono text-2xs uppercase tracking-wider text-fg-muted hover:text-fg underline-offset-2 hover:underline"
            >
                {open ? '▾ Ocultar detalhes' : '▸ Mostrar detalhes'}
            </button>
        </div>
    );
};

export const JobRow: React.FC<JobRowProps> = ({ job, statusKind, onOpen, onReuse, t }) => {
    return (
        <li
            role="listitem"
            className="group grid grid-cols-[2.25rem_1fr_auto] gap-4 py-3 hover:bg-surface-1/50 transition-colors duration-[120ms]"
        >
            <StatusDot kind={statusKind} size={8} className="self-center" />
            <div
                role="button"
                tabIndex={0}
                onClick={onOpen}
                onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onOpen();
                    }
                }}
                className="text-left min-w-0 cursor-pointer focus:outline-none focus-visible:bg-surface-1 focus-visible:ring-1 focus-visible:ring-accent"
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
                    {job.error && <ErrorLine error={job.error} />}
                </Stack>
            </div>
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
