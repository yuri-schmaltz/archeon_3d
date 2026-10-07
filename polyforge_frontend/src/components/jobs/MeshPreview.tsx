import React, { useEffect, useState } from 'react';

interface MeshPreviewProps {
    src: string;
    alt?: string;
    height?: number | string;
    autoRotate?: boolean;
}

/**
 * Renders a GLB in-page using Google's model-viewer custom
 * component (loaded lazily). Adds explicit loading and error UI
 * so a missing model (404, CORS, network failure) is communicated
 * instead of silently broken.
 */
export const MeshPreview: React.FC<MeshPreviewProps> = ({
    src,
    alt,
    height = 320,
    autoRotate = true,
}) => {
    const [ready, setReady] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [reducedMotion, setReducedMotion] = useState(false);

    useEffect(() => {
        if (typeof window === 'undefined' || !window.customElements) {
            queueMicrotask(() => setError('Custom elements are not supported in this browser.'));
            return;
        }
        // Lazy-load the model-viewer package so it does not inflate
        // the initial bundle. The package's side effect registers
        // the custom element.
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        import('@google/model-viewer').then(() => {
            const tryRegister = () => {
                if (cancelled) return;
                if (window.customElements.get('model-viewer')) {
                    queueMicrotask(() => setReady(true));
                } else {
                    timer = setTimeout(tryRegister, 50);
                }
            };
            tryRegister();
        }).catch((err: unknown) => {
            if (!cancelled) {
                const message = err instanceof Error ? err.message : 'Failed to load viewer.';
                queueMicrotask(() => setError(message));
            }
        });
        const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
        queueMicrotask(() => setReducedMotion(motionQuery.matches));
        const onMotion = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
        motionQuery.addEventListener('change', onMotion);
        return () => {
            cancelled = true;
            if (timer !== undefined) clearTimeout(timer);
            motionQuery.removeEventListener('change', onMotion);
        };
    }, []);

    const handleError = (event: Event) => {
        const detail = (event as CustomEvent<{ sourceError?: { message?: string } }>).detail;
        setError(detail?.sourceError?.message ?? 'Failed to load model.');
    };

    if (error) {
        return (
            <div
                className="bg-surface-1 border border-border rounded flex items-center justify-center text-center p-6"
                style={{ height }}
                role="alert"
            >
                <div className="space-y-2">
                    <p className="text-sm text-danger">{alt || 'mesh'} failed to load.</p>
                    <p className="text-xs text-fg-muted font-mono">{error}</p>
                    <a
                        href={src}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-accent underline text-sm"
                    >
                        Download instead
                    </a>
                </div>
            </div>
        );
    }

    if (!ready) {
        return (
            <div
                className="bg-surface-1 border border-border rounded flex items-center justify-center"
                style={{ height }}
            >
                <span className="text-xs text-fg-muted font-mono uppercase tracking-widest">
                    Loading viewer…
                </span>
            </div>
        );
    }

    return (
        <div
            className="bg-surface-1 border border-border rounded overflow-hidden relative"
            style={{ height }}
        >
            {/* @ts-expect-error — custom element typed in vite-env.d.ts */}
            <model-viewer
                src={src}
                alt={alt ?? 'Generated 3D mesh'}
                camera-controls
                auto-rotate={autoRotate && !reducedMotion}
                shadow-intensity="1"
                exposure="1"
                loading="lazy"
                reveal="auto"
                style={{ width: '100%', height: '100%' }}
                onError={handleError}
            />
        </div>
    );
};
