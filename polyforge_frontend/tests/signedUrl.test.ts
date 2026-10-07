import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('axios', () => {
    const mockGet = vi.fn();
    return {
        default: {
            isAxiosError: (err: unknown): boolean =>
                typeof err === 'object' && err !== null && (err as { isAxiosError?: boolean }).isAxiosError === true,
            get: mockGet,
        },
        isAxiosError: (err: unknown): boolean =>
            typeof err === 'object' && err !== null && (err as { isAxiosError?: boolean }).isAxiosError === true,
        get: mockGet,
    };
});

vi.mock('../src/api/client', () => {
    const mockGet = vi.fn();
    return {
        apiClient: { get: mockGet },
        API_URL: 'http://test/v1',
        BASE_URL: 'http://test',
        AUTH_REQUIRED_EVENT: 'polyforge:auth-required',
        LEGACY_AUTH_REQUIRED_EVENT: 'polyforge:auth-required',
        authHeaders: () => ({}),
        setApiKey: () => undefined,
        requestAuthentication: () => undefined,
        errorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
    };
});

import axios from 'axios';
import { apiClient } from '../src/api/client';

describe('signed URL fallback', () => {
    beforeEach(() => {
        (apiClient.get as ReturnType<typeof vi.fn>).mockReset();
    });

    it('returns the signed URL on success', async () => {
        (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
            data: { url: 'http://test/files/x.glb?token=v1.xxx&exp=999&nonce=n', expires_at: 999, ttl_seconds: 3600 },
        });
        // Re-import to pick up the mock
        const { signedDownloadUrl } = await import('../src/api/signedDownload');
        const url = await signedDownloadUrl('abc-123');
        expect(url).toContain('http://test/files/x.glb');
    });

    it('returns null on 503 (signing not configured)', async () => {
        const err = Object.assign(new Error('Service Unavailable'), {
            isAxiosError: true,
            response: { status: 503 },
        });
        (apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValueOnce(err);
        const { signedDownloadUrl } = await import('../src/api/signedDownload');
        const url = await signedDownloadUrl('abc-123');
        expect(url).toBeNull();
    });

    it('throws on non-503 errors', async () => {
        const err = Object.assign(new Error('Boom'), {
            isAxiosError: true,
            response: { status: 500 },
        });
        (apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValueOnce(err);
        const { signedDownloadUrl } = await import('../src/api/signedDownload');
        await expect(signedDownloadUrl('abc-123')).rejects.toThrow('Boom');
    });

    it('axios.isAxiosError guard works correctly', () => {
        expect(axios.isAxiosError({ isAxiosError: true })).toBe(true);
        expect(axios.isAxiosError(new Error('plain'))).toBe(false);
    });
});