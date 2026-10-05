import { useEffect, useSyncExternalStore } from 'react';

export type RouteId = 'create' | 'library' | 'system' | 'settings';

export interface RouteDef {
    id: RouteId;
    path: string;
    label: string;
    glyph: string;
}

export const ROUTES: RouteDef[] = [
    { id: 'create', path: '/criar', label: 'Criar', glyph: '+' },
    { id: 'library', path: '/biblioteca', label: 'Biblioteca', glyph: '☰' },
    { id: 'system', path: '/sistema', label: 'Sistema', glyph: '◧' },
    { id: 'settings', path: '/configuracoes', label: 'Ajustes', glyph: '⚙' },
];

function parseHash(): RouteId {
    if (typeof window === 'undefined') return 'create';
    const raw = window.location.hash.replace(/^#/, '').toLowerCase();
    const match = ROUTES.find((r) => raw === r.path || raw === `/${r.id}`);
    return match?.id ?? 'create';
}

function navigate(path: string, replace = false): void {
    if (typeof window === 'undefined') return;
    const target = `#${path}`;
    if (window.location.hash !== target) {
        if (replace) window.location.replace(target);
        else window.location.hash = target;
    }
}

const subscribe = (cb: () => void): (() => void) => {
    if (typeof window === 'undefined') return () => undefined;
    window.addEventListener('hashchange', cb);
    return () => window.removeEventListener('hashchange', cb);
};

const getSnapshot = (): RouteId => parseHash();

const getSnapshotSSR = (): RouteId => 'create';

export function useRoute(): RouteId {
    return useSyncExternalStore(subscribe, getSnapshot, getSnapshotSSR);
}

/** Helper for components to change the URL. */
export function go(route: RouteId, replace = false): void {
    const path = ROUTES.find((r) => r.id === route)?.path ?? '/criar';
    navigate(path, replace);
}

/** Patch initial hash on mount so deep links land at /criar by default. */
export function useEnsureDefaultRoute(): void {
    useEffect(() => {
        if (typeof window === 'undefined') return;
        if (!window.location.hash) navigate('/criar', true);
    }, []);
}
