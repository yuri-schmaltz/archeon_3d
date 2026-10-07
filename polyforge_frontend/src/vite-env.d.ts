/// <reference types="vite/client" />

interface ImportMetaEnv {
    /** Base URL of the PolyForge backend (no trailing slash, no /v1). */
    readonly VITE_API_URL: string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}

// Google <model-viewer> web component for in-browser 3D previews.
// Loaded via index.html; these declarations make it usable from JSX.
declare namespace JSX {
    interface ModelViewerAttributes extends React.HTMLAttributes<HTMLElement> {
        src?: string;
        alt?: string;
        'auto-rotate'?: boolean | string;
        'camera-controls'?: boolean | string;
        'shadow-intensity'?: string | number;
        exposure?: string | number;
        poster?: string;
        'environment-image'?: string;
    }
    interface IntrinsicElements {
        'model-viewer': ModelViewerAttributes;
    }
}
