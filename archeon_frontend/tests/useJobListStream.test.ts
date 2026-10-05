import { describe, expect, it } from 'vitest';
import { EMPTY_FALLBACK_JOBS, isJobList } from '../src/api/useJobListStream';

describe('useJobListStream defensive guard', () => {
    it('treats an array payload as a job list', () => {
        expect(isJobList([])).toBe(true);
        expect(isJobList([{ uid: 'abc' } as never])).toBe(true);
    });

    it('rejects non-array payloads (e.g. SPA HTML fallback when API is down)', () => {
        expect(isJobList('<!doctype html>...')).toBe(false);
        expect(isJobList({ items: [] })).toBe(false);
        expect(isJobList(null)).toBe(false);
        expect(isJobList(undefined)).toBe(false);
    });

    it('exports a stable empty fallback that callers can rely on', () => {
        expect(Array.isArray(EMPTY_FALLBACK_JOBS)).toBe(true);
        expect(EMPTY_FALLBACK_JOBS.length).toBe(0);
    });
});