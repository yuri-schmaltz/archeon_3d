import { useEffect, useState } from 'react';

export function useObjectUrl(file: File | null) {
    const [url, setUrl] = useState<string | null>(null);
    useEffect(() => {
        const next = file ? URL.createObjectURL(file) : null;
        // The URL belongs to this effect, so replacement and unmount both revoke it.
        // eslint-disable-next-line react-hooks/set-state-in-effect -- Blob URLs are browser resources acquired and released by this effect.
        setUrl(next);
        return () => { if (next) URL.revokeObjectURL(next); };
    }, [file]);
    return url;
}
