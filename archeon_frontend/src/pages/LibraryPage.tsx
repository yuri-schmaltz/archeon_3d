import React, { useEffect, useMemo, useState } from 'react';
import { apiClient, errorMessage, authHeaders } from '../api/client';
import { JobStatus, type JobResponse, type JobStatusType } from '../api/types';
import { useT } from '../i18n';
import {
    Text,
    Button,
    Stack,
    Divider,
    Pill,
    type StatusKind,
} from '../design/primitives';
import { setDetailUid } from '../hooks/useDetailUid';
import { JobRow } from '../components/library/JobRow';
import { go } from '../router';

const PAGE_SIZE = 20;

const STATUS_FILTERS: Array<{ key: 'all' | JobStatusType; i18n: string }> = [
    { key: 'all', i18n: 'library.filter.all' },
    { key: JobStatus.QUEUED, i18n: 'library.filter.queued' },
    { key: JobStatus.PROCESSING, i18n: 'library.filter.processing' },
    { key: JobStatus.COMPLETED, i18n: 'library.filter.completed' },
    { key: JobStatus.FAILED, i18n: 'library.filter.failed' },
    { key: JobStatus.CANCELLED, i18n: 'library.filter.cancelled' },
];

interface LibraryResponse {
    items: JobResponse[];
    total: number;
    page: number;
    page_size: number;
}

const kindByStatus: Record<JobStatusType, StatusKind> = {
    queued: 'queued',
    processing: 'live',
    completed: 'done',
    failed: 'failed',
    cancelled: 'cancelled',
};

export const LibraryPage: React.FC = () => {
    const t = useT();
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState<'all' | JobStatusType>('all');
    const [page, setPage] = useState(1);
    const [data, setData] = useState<LibraryResponse>({
        items: [],
        total: 0,
        page: 1,
        page_size: PAGE_SIZE,
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Debounce search input.
    const [debouncedSearch, setDebouncedSearch] = useState(search);
    useEffect(() => {
        const id = setTimeout(() => setDebouncedSearch(search), 250);
        return () => clearTimeout(id);
    }, [search]);

    // Reset to page 1 when filters change.
    useEffect(() => {
        setPage(1);
    }, [debouncedSearch, statusFilter]);

    const fetchPage = async (pageToLoad: number, currentStatus: typeof statusFilter, currentSearch: string) => {
        setLoading(true);
        setError(null);
        try {
            const params: Record<string, string | number> = {
                page: pageToLoad,
                page_size: PAGE_SIZE,
            };
            if (currentStatus !== 'all') params.status = currentStatus;
            if (currentSearch.trim()) params.q = currentSearch.trim();
            const response = await apiClient.get<LibraryResponse>(`/library`, {
                params,
                headers: authHeaders(),
            });
            // Defensive: backend unreachable may yield the SPA shell.
            if (response && typeof response.data === 'object' && Array.isArray(response.data.items)) {
                setData(response.data);
            } else {
                setError(t('library.error.unexpected'));
            }
        } catch (err) {
            setError(errorMessage(err));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        void fetchPage(page, statusFilter, debouncedSearch);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page, statusFilter, debouncedSearch]);

    const totalPages = useMemo(
        () => Math.max(1, Math.ceil(data.total / PAGE_SIZE)),
        [data.total],
    );

    const onReuse = (job: JobResponse) => {
        // Carry UID + mode to /criar so the form can pre-fill when mounted.
        window.location.hash = `#/criar?reuse=${encodeURIComponent(job.uid)}`;
    };

    return (
        <section className="space-y-6">
            <header className="space-y-1">
                <Text as="h1" voice="display" size="xl" tracking="tight">
                    {t('library.heading')}
                </Text>
                <Text voice="body" size="sm" tone="muted" className="leading-snug">
                    {t('library.heading.hint')}
                </Text>
            </header>

            <Stack gap={3}>
                    <input
                        type="search"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder={t('library.search')}
                        className="w-full bg-transparent text-fg border-b border-border-strong h-9 px-1 text-sm font-mono placeholder:text-fg-dim focus:outline-none focus:border-accent transition-colors duration-[120ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
                    />

                    <div
                        role="group"
                        aria-label="Filter jobs by status"
                        className="flex border-b border-border overflow-x-auto"
                    >
                        {STATUS_FILTERS.map((f) => {
                            const active = statusFilter === f.key;
                            return (
                                <button
                                    key={f.key}
                                    aria-pressed={active}
                                    onClick={() => setStatusFilter(f.key)}
                                    className={
                                            "px-4 h-10 flex items-center gap-2 " +
                                            "font-mono text-xs uppercase tracking-wider " +
                                            "border-b-2 -mb-px transition-colors duration-[120ms] " +
                                            (active
                                                ? "border-accent text-fg"
                                                : "border-transparent text-fg-muted hover:text-fg")
                                        }
                                >
                                    {t(f.i18n)}
                                </button>
                            );
                        })}
                    </div>
                </Stack>

                {error && (
                    <div role="alert" className="py-3">
                        <Pill tone="danger">{t('library.error')}: {error}</Pill>
                    </div>
                )}

                {data.items.length === 0 && !loading && !error && (
                    <div className="py-12 text-center text-fg-muted">
                        <Text voice="body" size="sm">
                            {t('library.empty')}
                        </Text>
                        <div className="mt-4">
                            <Button variant="ghost" size="sm" onClick={() => go('create')}>
                                +
                            </Button>
                        </div>
                    </div>
                )}

                <Divider />

                <ul className="divide-y divide-border" role="list">
                    {data.items.map((job) => (
                        <JobRow
                            key={job.uid}
                            job={job}
                            statusKind={kindByStatus[job.status]}
                            onOpen={() => setDetailUid(job.uid)}
                            onReuse={() => onReuse(job)}
                            t={t}
                        />
                    ))}
                </ul>

                {totalPages > 1 && (
                    <div className="flex items-center justify-between pt-4 border-t border-border">
                        <Button
                            variant="ghost"
                            size="sm"
                            disabled={page <= 1}
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                        >
                            ← {t('library.prev')}
                        </Button>
                        <Text voice="mono" size="2xs" tone="muted" tracking="wider" uppercase>
                            {t('library.pageOf', { page, total: totalPages })}
                        </Text>
                        <Button
                            variant="ghost"
                            size="sm"
                            disabled={page >= totalPages}
                            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                        >
                            {t('library.next')} →
                        </Button>
                    </div>
                )}
        </section>
    );
};

// Backward-compatible default export to keep tests working.
export default LibraryPage;
