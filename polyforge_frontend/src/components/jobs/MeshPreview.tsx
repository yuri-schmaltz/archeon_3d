import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useT } from '../../i18n';

type ViewMode = 'textured' | 'geometry' | 'wireframe';
type Environment = 'neutral' | 'studio' | 'outdoor' | 'custom';
type Background = 'transparent' | 'dark' | 'gradient';

interface MeshPreviewProps {
    src: string;
    alt?: string;
    height?: number | string;
    autoRotate?: boolean;
    showControls?: boolean;
}

/** Type assertion for model-viewer custom element properties */
type ModelViewerElement = HTMLElement & {
    model?: {
        materials: Array<{
            pbrMetallicRoughness: {
                baseColorTexture: { texture: unknown; setTexture: (t: unknown) => void };
                setMetallicFactor: (v: number) => void;
                setRoughnessFactor: (v: number) => void;
            };
        }>;
    };
    exposure: number;
    environmentImage: string;
    cameraOrbit: string;
    cameraTarget: string;
    activateAR?: () => void;
};

// Helper to safely access model-viewer properties
function getModelViewer(el: HTMLElement | null): ModelViewerElement | null {
    return el as ModelViewerElement | null;
}

/**
 * Renders a GLB in-page using Google's model-viewer custom
 * component (loaded lazily). Adds explicit loading and error UI
 * so a missing model (404, CORS, network failure) is communicated
 * instead of silently broken.
 *
 * Features:
 * - Toggle Appearance / Geometry / Wireframe modes
 * - Environment map selection (neutral, studio, outdoor)
 * - Background options (transparent, dark, gradient)
 * - AR quick access button
 * - Camera control hints overlay
 * - Reduced motion support
 */
export const MeshPreview: React.FC<MeshPreviewProps> = ({
    src,
    alt,
    height = 320,
    autoRotate = true,
    showControls = true,
}) => {
    const t = useT();
    const [ready, setReady] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [reducedMotion, setReducedMotion] = useState(false);
    const [viewMode, setViewMode] = useState<ViewMode>('textured');
    const [environment, setEnvironment] = useState<Environment>('neutral');
    const [background, setBackground] = useState<Background>('gradient');
    const [showHints, setShowHints] = useState(true);
    const [arSupported, setArSupported] = useState(false);
    const viewerRef = useRef<ModelViewerElement | null>(null);
    const materialStateRef = useRef<{ textures: unknown[]; exposure: number } | null>(null);

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

        // Check AR support
        queueMicrotask(() => {
            const mv = getModelViewer(document.createElement('model-viewer'));
            setArSupported(mv !== null && ('canLoadAR' in mv || 'activateAR' in mv));
        });

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

    const applyViewMode = useCallback((mode: ViewMode, viewer: ModelViewerElement) => {
        if (!viewer?.model?.materials) return;

        const materials = viewer.model.materials;

        if (mode === 'textured') {
            // Restore textures
            if (materialStateRef.current) {
                materials.forEach((mat, i) => {
                    const tex = materialStateRef.current!.textures[i];
                    if (tex) {
                        mat.pbrMetallicRoughness.baseColorTexture.setTexture(tex);
                    }
                });
                viewer.exposure = materialStateRef.current.exposure;
            }
            setEnvironment('neutral');
        } else if (mode === 'geometry') {
            // Save textures and remove them
            if (!materialStateRef.current) {
                materialStateRef.current = {
                    textures: materials.map(m => m.pbrMetallicRoughness.baseColorTexture.texture),
                    exposure: viewer.exposure || 1,
                };
            }
            materials.forEach(mat => {
                mat.pbrMetallicRoughness.baseColorTexture.setTexture(null);
            });
            viewer.exposure = 4;
            setEnvironment('studio');
        } else if (mode === 'wireframe') {
            // Show wireframe by setting all materials to unlit
            materials.forEach(mat => {
                mat.pbrMetallicRoughness.setMetallicFactor(0);
                mat.pbrMetallicRoughness.setRoughnessFactor(1);
            });
            viewer.exposure = 1.5;
        }
    }, []);

    const handleViewerLoad = useCallback((event: Event) => {
        const viewer = getModelViewer(event.target as HTMLElement);
        if (!viewer) return;
        viewerRef.current = viewer;

        // Initialize material state
        if (viewer.model?.materials?.length) {
            materialStateRef.current = {
                textures: viewer.model.materials.map(m => m.pbrMetallicRoughness.baseColorTexture.texture),
                exposure: viewer.exposure || 1,
            };
        }

        // Apply initial view mode
        if (viewMode !== 'textured') {
            applyViewMode(viewMode, viewer);
        }

        // Hide hints after first interaction
        const onInteract = () => {
            setShowHints(false);
            viewer.removeEventListener('camera-change', onInteract);
        };
        viewer.addEventListener('camera-change', onInteract);
    }, [viewMode, applyViewMode]);

    const handleViewModeChange = useCallback((mode: ViewMode) => {
        setViewMode(mode);
        if (viewerRef.current) {
            applyViewMode(mode, viewerRef.current);
        }
    }, [applyViewMode]);

    const handleEnvironmentChange = useCallback((env: Environment) => {
        setEnvironment(env);
        const viewer = getModelViewer(viewerRef.current);
        if (viewer) {
            const envMap: Record<Environment, string> = {
                neutral: 'neutral',
                studio: 'neutral', // Uses model-viewer's built-in neutral environment
                outdoor: 'neutral', // Uses model-viewer's built-in neutral environment
                custom: '/env_maps/gradient.jpg',
            };
            viewer.environmentImage = envMap[env];
        }
    }, []);

    const handleAr = useCallback(() => {
        const viewer = getModelViewer(viewerRef.current);
        viewer?.activateAR?.();
    }, []);

    const handleResetCamera = useCallback(() => {
        const viewer = getModelViewer(viewerRef.current);
        if (viewer) {
            viewer.cameraOrbit = '0deg 90deg 12m';
            viewer.cameraTarget = '0m 0m 0m';
        }
    }, []);

    const backgroundClass: Record<Background, string> = {
        transparent: 'bg-transparent',
        dark: 'bg-stone-950',
        gradient: 'bg-gradient-to-b from-stone-900 to-stone-950',
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
                        {t('viewer.downloadInstead') || 'Download instead'}
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
                    {t('viewer.loading') || 'Loading viewer…'}
                </span>
            </div>
        );
    }

    return (
        <div
            className={`border border-border rounded overflow-hidden relative ${backgroundClass[background]}`}
            style={{ height }}
        >
            {/* Camera control hints overlay */}
            {showHints && !reducedMotion && (
                <div className="absolute top-2 right-2 z-20 flex flex-col gap-1 text-xs font-mono text-stone-400 bg-stone-950/80 px-2 py-1.5 rounded">
                    <span>⟳ drag to rotate</span>
                    <span>⊡ scroll to zoom</span>
                    <span>⊞ right-click to pan</span>
                    <button
                        onClick={() => setShowHints(false)}
                        className="text-stone-500 hover:text-stone-300 text-center mt-1"
                    >
                        ✕
                    </button>
                </div>
            )}

            {/* Control bar */}
            {showControls && (
                <div className="absolute top-2 left-2 z-10 flex flex-wrap gap-1">
                    {/* View mode toggle */}
                    <div className="flex bg-stone-900/90 rounded overflow-hidden">
                        <button
                            onClick={() => handleViewModeChange('textured')}
                            className={`px-2 py-1 text-xs font-mono uppercase tracking-wider transition-colors ${
                                viewMode === 'textured' ? 'bg-accent text-stone-950' : 'text-stone-400 hover:text-stone-200'
                            }`}
                            title={t('viewer.textured') || 'Appearance'}
                        >
                            ◉
                        </button>
                        <button
                            onClick={() => handleViewModeChange('geometry')}
                            className={`px-2 py-1 text-xs font-mono uppercase tracking-wider transition-colors ${
                                viewMode === 'geometry' ? 'bg-accent text-stone-950' : 'text-stone-400 hover:text-stone-200'
                            }`}
                            title={t('viewer.geometry') || 'Geometry'}
                        >
                            ◇
                        </button>
                        <button
                            onClick={() => handleViewModeChange('wireframe')}
                            className={`px-2 py-1 text-xs font-mono uppercase tracking-wider transition-colors ${
                                viewMode === 'wireframe' ? 'bg-accent text-stone-950' : 'text-stone-400 hover:text-stone-200'
                            }`}
                            title={t('viewer.wireframe') || 'Wireframe'}
                        >
                            ⬡
                        </button>
                    </div>

                    {/* Environment toggle */}
                    <div className="flex bg-stone-900/90 rounded overflow-hidden">
                        {(['neutral', 'studio', 'outdoor'] as Environment[]).map((env) => (
                            <button
                                key={env}
                                onClick={() => handleEnvironmentChange(env)}
                                className={`px-2 py-1 text-xs font-mono uppercase tracking-wider transition-colors ${
                                    environment === env ? 'bg-accent text-stone-950' : 'text-stone-400 hover:text-stone-200'
                                }`}
                                title={t(`viewer.env.${env}`) || env}
                            >
                                {env === 'neutral' ? '☀' : env === 'studio' ? '◫' : '⛰'}
                            </button>
                        ))}
                    </div>

                    {/* Background toggle */}
                    <div className="flex bg-stone-900/90 rounded overflow-hidden">
                        {(['transparent', 'dark', 'gradient'] as Background[]).map((bg) => (
                            <button
                                key={bg}
                                onClick={() => setBackground(bg)}
                                className={`px-2 py-1 text-xs font-mono uppercase tracking-wider transition-colors ${
                                    background === bg ? 'bg-accent text-stone-950' : 'text-stone-400 hover:text-stone-200'
                                }`}
                                title={t(`viewer.bg.${bg}`) || bg}
                            >
                                {bg === 'transparent' ? '□' : bg === 'dark' ? '■' : '▤'}
                            </button>
                        ))}
                    </div>

                    {/* Camera reset */}
                    <button
                        onClick={handleResetCamera}
                        className="px-2 py-1 text-xs font-mono bg-stone-900/90 text-stone-400 hover:text-stone-200 rounded transition-colors"
                        title={t('viewer.resetCamera') || 'Reset camera'}
                    >
                        ⌂
                    </button>

                    {/* AR button */}
                    {arSupported && (
                        <button
                            onClick={handleAr}
                            className="px-2 py-1 text-xs font-mono bg-stone-900/90 text-stone-400 hover:text-stone-200 rounded transition-colors"
                            title={t('viewer.ar') || 'View in AR'}
                        >
                            AR
                        </button>
                    )}
                </div>
            )}

            {/* @ts-expect-error — custom element typed in vite-env.d.ts */}
            <model-viewer
                src={src}
                alt={alt ?? 'Generated 3D mesh'}
                camera-controls
                auto-rotate={autoRotate && !reducedMotion}
                shadow-intensity="1"
                exposure="1"
                environment-image="neutral"
                loading="lazy"
                reveal="auto"
                ar-modes="webxr scene-viewer quick-look"
                style={{ width: '100%', height: '100%' }}
                onError={handleError}
                onLoad={handleViewerLoad}
            />
        </div>
    );
};
