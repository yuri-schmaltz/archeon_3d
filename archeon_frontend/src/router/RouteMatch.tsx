import React from 'react';
import { useRoute, type RouteId } from './index';

/** React-friendly route prop. Children render when the current route matches. */
export function RouteMatch({
    id,
    children,
}: {
    id: RouteId;
    children: React.ReactNode;
}): React.ReactElement | null {
    const current = useRoute();
    if (current !== id) return null;
    return <>{children}</>;
}
