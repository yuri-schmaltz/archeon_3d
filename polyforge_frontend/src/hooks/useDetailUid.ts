import { useSyncExternalStore } from 'react';

const listeners = new Set<() => void>();
let currentUid: string | null = null;

function subscribe(cb: () => void): () => void {
    listeners.add(cb);
    return () => listeners.delete(cb);
}

function getSnapshot(): string | null {
    return currentUid;
}

export function setDetailUid(uid: string | null): void {
    currentUid = uid;
    listeners.forEach((cb) => cb());
}

export function useDetailUid(): [string | null, () => void] {
    const uid = useSyncExternalStore(subscribe, getSnapshot, () => null);
    return [uid, () => setDetailUid(null)];
}
