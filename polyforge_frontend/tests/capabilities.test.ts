import { describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

// Mock the apiClient so we don't hit the network.
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

import { apiClient } from '../src/api/client';
import { useCapabilities, FALLBACK_CAPABILITIES } from '../src/api/capabilities';

const mockGet = apiClient.get as unknown as ReturnType<typeof vi.fn>;

describe('useCapabilities', () => {
    it('starts with the fallback and replaces it when /v1/capabilities responds', async () => {
        mockGet.mockResolvedValueOnce({
            data: {
                modes: {
                    text: { available: false, reason: 'no text2image', requires: ['text_to_image'] },
                    image: { available: true, reason: null, requires: [] },
                    multiview: { available: false, reason: 'no model', requires: [] },
                    texture: { available: true, reason: null, requires: [] },
                },
                models: {},
                presets: {
                    fast: { steps: 5, guidance: 5.0, octree_resolution: 192 },
                    balanced: { steps: 50, guidance: 5.0, octree_resolution: 256 },
                    detailed: { steps: 100, guidance: 7.5, octree_resolution: 384 },
                },
                limits: {
                    image_bytes: 10 * 1024 * 1024,
                    mesh_bytes: 30 * 1024 * 1024,
                    queue_depth: 64,
                    body_bytes: 64 * 1024 * 1024,
                },
                version: '2.1.0.post7',
            },
        });
        const { result } = renderHook(() => useCapabilities());
        await waitFor(() => {
            expect(result.current.loading).toBe(false);
        });
        expect(result.current.capabilities.modes.text.available).toBe(false);
        expect(result.current.capabilities.modes.image.available).toBe(true);
        expect(result.current.capabilities.version).toBe('2.1.0.post7');
    });

    it('falls back gracefully when the request fails', async () => {
        mockGet.mockRejectedValueOnce(new Error('boom'));
        const { result } = renderHook(() => useCapabilities());
        await waitFor(() => {
            expect(result.current.loading).toBe(false);
        });
        expect(result.current.error).toContain('boom');
        // The fallback keeps every mode available so the UI stays usable.
        expect(result.current.capabilities).toEqual(FALLBACK_CAPABILITIES);
    });
});
