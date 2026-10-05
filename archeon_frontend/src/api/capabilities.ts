import { useEffect, useReducer } from 'react';
import { apiClient, API_URL, authHeaders } from './client';

export interface ModeCapability {
    available: boolean;
    reason: string | null;
    requires: string[];
}

export interface ModelInfo {
    id: string;
    subfolder: string | null;
    loaded: boolean;
}

export interface PresetInfo {
    steps: number;
    guidance: number;
    octree_resolution: number;
}

export interface CapabilityLimits {
    image_bytes: number;
    mesh_bytes: number;
    queue_depth: number;
    body_bytes: number;
}

export interface Capabilities {
    modes: Record<'text' | 'image' | 'multiview' | 'texture', ModeCapability>;
    models: Record<string, ModelInfo>;
    presets: Record<'fast' | 'balanced' | 'detailed', PresetInfo>;
    limits: CapabilityLimits;
    version: string;
}

const fallback: Capabilities = {
    modes: {
        text: { available: true, reason: null, requires: [] },
        image: { available: true, reason: null, requires: [] },
        multiview: { available: true, reason: null, requires: [] },
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
    version: 'unknown',
};

interface State {
    capabilities: Capabilities;
    loading: boolean;
    error: string | null;
    nonce: number;
}

type Action =
    | { type: 'fetch-start' }
    | { type: 'fetch-success'; payload: Capabilities }
    | { type: 'fetch-failure'; error: string }
    | { type: 'refetch' };

function reducer(state: State, action: Action): State {
    switch (action.type) {
    case 'fetch-start':
        return { ...state, loading: true };
    case 'fetch-success':
        return { capabilities: action.payload, loading: false, error: null, nonce: state.nonce };
    case 'fetch-failure':
        return { capabilities: state.capabilities, loading: false, error: action.error, nonce: state.nonce };
    case 'refetch':
        return { ...state, nonce: state.nonce + 1, loading: true };
    default:
        return state;
    }
}

/**
 * Read /v1/capabilities once on mount. When the request fails (auth not
 * yet established, server unreachable) we keep the previous value (or
 * the permissive fallback) so the UI remains functional; the real
 * capabilities will arrive as soon as the gate clears.
 */
export function useCapabilities(): {
    capabilities: Capabilities;
    loading: boolean;
    error: string | null;
    refetch: () => void;
} {
    const [state, dispatch] = useReducer(reducer, {
        capabilities: fallback,
        loading: true,
        error: null,
        nonce: 0,
    });

    useEffect(() => {
        let active = true;
        dispatch({ type: 'fetch-start' });
        void apiClient
            .get<Capabilities>('/capabilities', { headers: authHeaders() })
            .then((response) => {
                if (!active) return;
                dispatch({ type: 'fetch-success', payload: response.data });
            })
            .catch((err: unknown) => {
                if (!active) return;
                const message = err instanceof Error ? err.message : String(err);
                dispatch({ type: 'fetch-failure', error: message });
            });
        return () => {
            active = false;
        };
    }, [state.nonce]);

    return {
        capabilities: state.capabilities,
        loading: state.loading,
        error: state.error,
        refetch: () => dispatch({ type: 'refetch' }),
    };
}

/** Exposed for tests + non-React callers. */
export const CAPABILITIES_URL = `${API_URL}/capabilities`;
export { fallback as FALLBACK_CAPABILITIES };
