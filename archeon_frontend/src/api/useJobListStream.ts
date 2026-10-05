import type { JobResponse } from './types';
import { useJobFeed } from './useJobFeed';

export const EMPTY_FALLBACK_JOBS: JobResponse[] = [];

export function isJobList(value: unknown): value is JobResponse[] {
    return Array.isArray(value);
}

export function useJobListStream(_baseUrl: string, opts: { pollIntervalMs?: number; enabled?: boolean } = {}) {
    const { data, ...state } = useJobFeed<JobResponse[]>('/jobs', 'list', opts);
    const jobs = isJobList(data) ? data : EMPTY_FALLBACK_JOBS;
    return { jobs, ...state };
}
