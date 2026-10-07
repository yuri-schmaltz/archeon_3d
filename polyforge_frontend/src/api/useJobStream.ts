import { JobStatus, type JobResponse } from './types';
import { useJobFeed } from './useJobFeed';

const terminal = (job: JobResponse) => job.status === JobStatus.COMPLETED
    || job.status === JobStatus.FAILED || job.status === JobStatus.CANCELLED;
export function useJobStream(_baseUrl: string, uid: string | null,
    opts: { pollIntervalMs?: number; enabled?: boolean } = {}) {
    const { data: job, ...state } = useJobFeed<JobResponse>(`/jobs/${uid ?? ''}`, 'status', {
        ...opts, enabled: !!uid && opts.enabled !== false, terminal,
    });
    return { job, status: job?.status ?? null, ...state };
}
